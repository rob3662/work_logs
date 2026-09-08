# === LICENSE HEADER START ===
# Copyright (c) 2026 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

"""Work log routes: tenant-scoped sessions and tasks."""

import csv
import io
import logging
import os
from datetime import date, datetime, time as time_type, timedelta
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    session as flask_session,
    url_for,
)
from flask_login import current_user, login_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from database import execute_query
from email_service import send_template_email
from invites import create_invite, list_invites_for_tenant, revoke_invite
from security import log_security_event, rate_limit, sanitize_input
from stripe_payments_import import (
    DEFAULT_BALANCE_FEE_PROJECT,
    MAX_CSV_BYTES,
    StripeBalanceFeeRow,
    StripePaymentRow,
    build_balance_fee_review_rows,
    build_review_rows,
    detect_stripe_csv_kind,
    normalize_descriptor,
    parse_balance_history_csv,
    parse_unified_payments_csv,
)

logger = logging.getLogger(__name__)

work_bp = Blueprint("work", __name__, url_prefix="/work")


def _parse_date(s: str) -> date | None:
    if not s or not str(s).strip():
        return None
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


def _parse_time(s: str) -> time_type | None:
    if not s or not str(s).strip():
        return None
    raw = str(s).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _hours_from_times(d: date, start_t: time_type, end_t: time_type) -> Decimal:
    a = datetime.combine(d, start_t)
    b = datetime.combine(d, end_t)
    secs = (b - a).total_seconds()
    if secs < 0:
        secs = 0
    return Decimal(str(round(secs / 3600.0, 2)))


def _end_time_from_start_plus_hours(work_date: date, start_t: time_type, hours: Decimal) -> time_type:
    """Clock time after adding fractional hours to start on work_date (may cross midnight)."""
    start_dt = datetime.combine(work_date, start_t)
    seconds = float(hours) * 3600.0
    end_dt = start_dt + timedelta(seconds=seconds)
    return end_dt.time()


def _optional_decimal(s: str) -> Decimal | None:
    if s is None or str(s).strip() == "":
        return None
    try:
        return Decimal(str(s).strip())
    except InvalidOperation:
        return None


def _get_session(tenant_id: int, session_id: int):
    return execute_query(
        """
        SELECT * FROM work_sessions
        WHERE id = %s AND tenant_id = %s
        LIMIT 1
        """,
        (session_id, tenant_id),
        fetch_one=True,
    )


def _active_session_for_user(tenant_id: int, user_id: int):
    return execute_query(
        """
        SELECT * FROM work_sessions
        WHERE tenant_id = %s AND user_id = %s AND end_time IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (tenant_id, user_id),
        fetch_one=True,
    )


def _username_for_user(tenant_id: int, user_id) -> str | None:
    if user_id is None:
        return None
    row = execute_query(
        """
        SELECT username FROM users
        WHERE id = %s AND tenant_id = %s
        LIMIT 1
        """,
        (user_id, tenant_id),
        fetch_one=True,
    )
    return (row or {}).get("username")


def _current_user_is_tenant_owner() -> bool:
    row = execute_query(
        "SELECT owner_user_id FROM tenants WHERE id = %s LIMIT 1",
        (current_user.tenant_id,),
        fetch_one=True,
    )
    oid = row.get("owner_user_id") if row else None
    if oid is None:
        return bool(getattr(current_user, "is_admin", False))
    return int(oid) == int(current_user.id)


def _can_edit_session(sess: dict) -> bool:
    if not sess:
        return False
    return sess.get("user_id") == current_user.id or current_user.is_admin


def _get_task(tenant_id: int, task_id: int):
    return execute_query(
        """
        SELECT * FROM work_tasks
        WHERE id = %s AND tenant_id = %s
        LIMIT 1
        """,
        (task_id, tenant_id),
        fetch_one=True,
    )


def _recompute_session_expenses_from_lines(tenant_id: int, session_id: int) -> None:
    row = execute_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS s
        FROM work_expense_items
        WHERE tenant_id = %s AND session_id = %s
        """,
        (tenant_id, session_id),
        fetch_one=True,
    )
    total = row["s"] if row is not None else Decimal("0")
    execute_query(
        """
        UPDATE work_sessions
        SET expenses = %s, updated_at = %s
        WHERE id = %s AND tenant_id = %s
        """,
        (total, datetime.utcnow(), session_id, tenant_id),
        fetch_all=False,
    )


def _recompute_session_income_from_lines(tenant_id: int, session_id: int) -> None:
    row = execute_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS s
        FROM work_income_items
        WHERE tenant_id = %s AND session_id = %s
        """,
        (tenant_id, session_id),
        fetch_one=True,
    )
    total = row["s"] if row is not None else Decimal("0")
    execute_query(
        """
        UPDATE work_sessions
        SET income = %s, updated_at = %s
        WHERE id = %s AND tenant_id = %s
        """,
        (total, datetime.utcnow(), session_id, tenant_id),
        fetch_all=False,
    )


def _session_has_income_lines(tenant_id: int, session_id: int) -> bool:
    r = execute_query(
        """
        SELECT 1 FROM work_income_items
        WHERE tenant_id = %s AND session_id = %s
        LIMIT 1
        """,
        (tenant_id, session_id),
        fetch_one=True,
    )
    return r is not None


def _session_has_expense_lines(tenant_id: int, session_id: int) -> bool:
    r = execute_query(
        """
        SELECT 1 FROM work_expense_items
        WHERE tenant_id = %s AND session_id = %s
        LIMIT 1
        """,
        (tenant_id, session_id),
        fetch_one=True,
    )
    return r is not None


def _session_income_lines_sum(tenant_id: int, session_id: int):
    row = execute_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS s
        FROM work_income_items
        WHERE tenant_id = %s AND session_id = %s
        """,
        (tenant_id, session_id),
        fetch_one=True,
    )
    return row["s"] if row is not None else Decimal("0")


def _session_expense_lines_sum(tenant_id: int, session_id: int):
    row = execute_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS s
        FROM work_expense_items
        WHERE tenant_id = %s AND session_id = %s
        """,
        (tenant_id, session_id),
        fetch_one=True,
    )
    return row["s"] if row is not None else Decimal("0")


def _report_date_defaults():
    today = date.today()
    start = date(today.year, today.month, 1)
    return start, today


def _report_generic_default_from() -> date:
    """Sunday on or before (today - 28 days); for generic report default range (weeks start Sunday)."""
    today = date.today()
    anchor = today - timedelta(days=28)
    days_since_sunday = (anchor.weekday() + 1) % 7
    return anchor - timedelta(days=days_since_sunday)


def _fetch_report_rows(tenant_id: int, date_from: date, date_to: date, project_filter: str):
    pf = (project_filter or "").strip()
    if pf:
        return execute_query(
            """
            SELECT id, project, work_date, start_time, end_time, hours_worked,
                   income, expenses, notes, created_at
            FROM work_sessions
            WHERE tenant_id = %s
              AND work_date >= %s AND work_date <= %s
              AND project ILIKE %s
            ORDER BY work_date ASC, id ASC
            """,
            (tenant_id, date_from, date_to, f"%{pf}%"),
            fetch_all=True,
        ) or []
    return execute_query(
        """
        SELECT id, project, work_date, start_time, end_time, hours_worked,
               income, expenses, notes, created_at
        FROM work_sessions
        WHERE tenant_id = %s
          AND work_date >= %s AND work_date <= %s
        ORDER BY work_date ASC, id ASC
        """,
        (tenant_id, date_from, date_to),
        fetch_all=True,
    ) or []


def _fetch_report_totals(tenant_id: int, date_from: date, date_to: date, project_filter: str):
    pf = (project_filter or "").strip()
    if pf:
        row = execute_query(
            """
            SELECT
                COALESCE(SUM(hours_worked), 0) AS hours_sum,
                COALESCE(SUM(income), 0) AS income_sum,
                COALESCE(SUM(expenses), 0) AS expenses_sum
            FROM work_sessions
            WHERE tenant_id = %s
              AND work_date >= %s AND work_date <= %s
              AND project ILIKE %s
            """,
            (tenant_id, date_from, date_to, f"%{pf}%"),
            fetch_one=True,
        )
    else:
        row = execute_query(
            """
            SELECT
                COALESCE(SUM(hours_worked), 0) AS hours_sum,
                COALESCE(SUM(income), 0) AS income_sum,
                COALESCE(SUM(expenses), 0) AS expenses_sum
            FROM work_sessions
            WHERE tenant_id = %s
              AND work_date >= %s AND work_date <= %s
            """,
            (tenant_id, date_from, date_to),
            fetch_one=True,
        )
    return row or {}


def _ei_weekly_summary(tenant_id: int, date_from: date, date_to: date, project_filter: str) -> list:
    """
    Four Sunday-based weeks (Sun–Sat) ending at the week that contains date_to.
    Each row sums hours and income for sessions in that week intersected with [date_from, date_to].
    Rows are ordered oldest week first.
    """
    pf = (project_filter or "").strip()
    anchor_sunday = date_to - timedelta((date_to.weekday() + 1) % 7)
    out = []
    for weeks_back in (3, 2, 1, 0):
        ws = anchor_sunday - timedelta(weeks=weeks_back)
        we = ws + timedelta(days=6)
        eff_from = max(ws, date_from)
        eff_to = min(we, date_to)
        if eff_from > eff_to:
            h = Decimal("0")
            inc = Decimal("0")
        elif pf:
            row = execute_query(
                """
                SELECT COALESCE(SUM(hours_worked), 0) AS h,
                       COALESCE(SUM(income), 0) AS inc
                FROM work_sessions
                WHERE tenant_id = %s
                  AND work_date >= %s AND work_date <= %s
                  AND project ILIKE %s
                """,
                (tenant_id, eff_from, eff_to, f"%{pf}%"),
                fetch_one=True,
            )
            h = (row or {}).get("h") or Decimal("0")
            inc = (row or {}).get("inc") or Decimal("0")
        else:
            row = execute_query(
                """
                SELECT COALESCE(SUM(hours_worked), 0) AS h,
                       COALESCE(SUM(income), 0) AS inc
                FROM work_sessions
                WHERE tenant_id = %s
                  AND work_date >= %s AND work_date <= %s
                """,
                (tenant_id, eff_from, eff_to),
                fetch_one=True,
            )
            h = (row or {}).get("h") or Decimal("0")
            inc = (row or {}).get("inc") or Decimal("0")
        out.append({"week_sunday": ws, "hours": h, "gross_income": inc})
    return out


@work_bp.route("/sessions")
@login_required
def sessions_list():
    rows = execute_query(
        """
        SELECT ws.id, ws.project, ws.work_date, ws.start_time, ws.end_time,
               ws.hours_worked, ws.income, ws.expenses, ws.user_id,
               u.username AS started_by_username
        FROM work_sessions ws
        LEFT JOIN users u ON u.id = ws.user_id AND u.tenant_id = ws.tenant_id
        WHERE ws.tenant_id = %s
        ORDER BY ws.work_date DESC, ws.start_time DESC, ws.id DESC
        LIMIT 200
        """,
        (current_user.tenant_id,),
        fetch_all=True,
    )
    return render_template("work/sessions_list.html", sessions=rows or [])


@work_bp.route("/sessions/new", methods=["GET", "POST"])
@login_required
@rate_limit("30 per minute")
def session_new():
    active = _active_session_for_user(current_user.tenant_id, current_user.id)
    if request.method == "POST":
        if active:
            flash("You already have an open session. Stop it before starting another.", "error")
            return redirect(url_for("work.session_detail", session_id=active["id"]))

        project = sanitize_input(request.form.get("project", "").strip(), max_length=200)
        if not project:
            flash("Project is required.", "error")
            return render_template("work/session_form.html", active=active)

        work_date = _parse_date(request.form.get("work_date", ""))
        if not work_date:
            flash("Work date is required (YYYY-MM-DD).", "error")
            return render_template("work/session_form.html", active=active)

        start_time = _parse_time(request.form.get("start_time", ""))
        if not start_time:
            flash("Start time is required.", "error")
            return render_template("work/session_form.html", active=active)

        notes = sanitize_input(request.form.get("notes", ""), max_length=8000)

        row = execute_query(
            """
            INSERT INTO work_sessions (
                tenant_id, user_id, project, work_date, start_time, end_time,
                hours_worked, notes, income, expenses, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, NULL, NULL, %s, NULL, NULL, %s, %s)
            RETURNING id
            """,
            (
                current_user.tenant_id,
                current_user.id,
                project,
                work_date,
                start_time,
                notes,
                datetime.utcnow(),
                datetime.utcnow(),
            ),
            fetch_one=True,
        )
        if not row:
            flash("Could not create session.", "error")
            return render_template("work/session_form.html", active=active)
        flash("Session started.", "success")
        return redirect(url_for("work.session_detail", session_id=row["id"]))

    return render_template("work/session_form.html", active=active)


@work_bp.route("/sessions/<int:session_id>")
@login_required
def session_detail(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    tid = current_user.tenant_id
    started_by_username = _username_for_user(tid, sess.get("user_id"))
    ended_by_username = _username_for_user(tid, sess.get("ended_by_user_id"))
    tasks = execute_query(
        """
        SELECT wt.id, wt.task_text, wt.created_at, wt.user_id,
               u.username AS added_by_username
        FROM work_tasks wt
        LEFT JOIN users u ON u.id = wt.user_id AND u.tenant_id = wt.tenant_id
        WHERE wt.tenant_id = %s AND wt.session_id = %s
        ORDER BY wt.id ASC
        """,
        (tid, session_id),
        fetch_all=True,
    )
    expense_items = execute_query(
        """
        SELECT id, amount, description, stripe_charge_id, source, created_at
        FROM work_expense_items
        WHERE tenant_id = %s AND session_id = %s
        ORDER BY id ASC
        """,
        (tid, session_id),
        fetch_all=True,
    )
    income_items = execute_query(
        """
        SELECT id, amount, description, fee_amount, stripe_charge_id, currency,
               statement_descriptor, customer_email, source, created_at
        FROM work_income_items
        WHERE tenant_id = %s AND session_id = %s
        ORDER BY id ASC
        """,
        (tid, session_id),
        fetch_all=True,
    )
    return render_template(
        "work/session_detail.html",
        session=sess,
        tasks=tasks or [],
        expense_items=expense_items or [],
        income_items=income_items or [],
        started_by_username=started_by_username,
        ended_by_username=ended_by_username,
        can_edit=_can_edit_session(sess),
        can_delete_session=_current_user_is_tenant_owner(),
    )


@work_bp.route("/sessions/<int:session_id>/stop", methods=["POST"])
@login_required
@rate_limit("60 per minute")
def session_stop(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if not _can_edit_session(sess):
        flash("You cannot stop this session.", "error")
        return redirect(url_for("work.sessions_list"))
    if sess.get("end_time") is not None:
        flash("This session is already closed.", "info")
        return redirect(url_for("work.session_detail", session_id=session_id))

    hours_override = _optional_decimal(request.form.get("hours_worked", ""))
    end_time = _parse_time(request.form.get("end_time", ""))

    work_date = sess["work_date"]
    if isinstance(work_date, str):
        work_date = _parse_date(work_date)
    start_t = sess["start_time"]
    if not work_date or not start_t:
        flash("Session is missing work date or start time.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))

    if hours_override is not None:
        if hours_override < 0:
            flash("Hours must be zero or positive.", "error")
            return redirect(url_for("work.session_detail", session_id=session_id))
        hours_worked = hours_override
        end_time = _end_time_from_start_plus_hours(work_date, start_t, hours_worked)
    else:
        if not end_time:
            flash("End time is required, or enter hours under “Hours (optional override)”.", "error")
            return redirect(url_for("work.session_detail", session_id=session_id))
        hours_worked = _hours_from_times(work_date, start_t, end_time)

    execute_query(
        """
        UPDATE work_sessions
        SET end_time = %s, hours_worked = %s, ended_by_user_id = %s, updated_at = %s
        WHERE id = %s AND tenant_id = %s
        """,
        (
            end_time,
            hours_worked,
            current_user.id,
            datetime.utcnow(),
            session_id,
            current_user.tenant_id,
        ),
        fetch_all=False,
    )
    flash("Session stopped.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


@work_bp.route("/sessions/<int:session_id>/delete", methods=["POST"])
@login_required
@rate_limit("30 per minute")
def session_delete(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if not _current_user_is_tenant_owner():
        flash("Only the tenant owner can delete a session.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    execute_query(
        """
        DELETE FROM work_sessions
        WHERE id = %s AND tenant_id = %s
        """,
        (session_id, current_user.tenant_id),
        fetch_all=False,
    )
    log_security_event(
        "work_session_deleted",
        current_user.id,
        {"session_id": session_id, "tenant_id": current_user.tenant_id},
    )
    flash("Session deleted.", "success")
    return redirect(url_for("work.sessions_list"))


@work_bp.route("/sessions/<int:session_id>/task", methods=["POST"])
@login_required
@rate_limit("60 per minute")
def session_add_task(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    text = sanitize_input(request.form.get("task_text", "").strip(), max_length=4000)
    if not text:
        flash("Task text is required.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    execute_query(
        """
        INSERT INTO work_tasks (tenant_id, session_id, user_id, task_text, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            current_user.tenant_id,
            session_id,
            current_user.id,
            text,
            datetime.utcnow(),
            datetime.utcnow(),
        ),
        fetch_all=False,
    )
    flash("Task added.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


@work_bp.route("/sessions/<int:session_id>/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
@rate_limit("60 per minute")
def task_edit(session_id: int, task_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    task = _get_task(current_user.tenant_id, task_id)
    if not task or int(task["session_id"]) != session_id:
        flash("Task not found.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    if task.get("user_id") != current_user.id and not current_user.is_admin:
        flash("You cannot edit this task.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))

    if request.method == "POST":
        text = sanitize_input(request.form.get("task_text", "").strip(), max_length=4000)
        if not text:
            flash("Task text is required.", "error")
            return render_template("work/task_edit.html", session=sess, task=task)
        execute_query(
            """
            UPDATE work_tasks
            SET task_text = %s, updated_at = %s
            WHERE id = %s AND tenant_id = %s AND session_id = %s
            """,
            (text, datetime.utcnow(), task_id, current_user.tenant_id, session_id),
            fetch_all=False,
        )
        flash("Task updated.", "success")
        return redirect(url_for("work.session_detail", session_id=session_id))

    return render_template("work/task_edit.html", session=sess, task=task)


@work_bp.route("/sessions/<int:session_id>/tasks/<int:task_id>/delete", methods=["POST"])
@login_required
@rate_limit("60 per minute")
def task_delete(session_id: int, task_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    task = _get_task(current_user.tenant_id, task_id)
    if not task or int(task["session_id"]) != session_id:
        flash("Task not found.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    if task.get("user_id") != current_user.id and not current_user.is_admin:
        flash("You cannot delete this task.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    execute_query(
        """
        DELETE FROM work_tasks
        WHERE id = %s AND tenant_id = %s AND session_id = %s
        """,
        (task_id, current_user.tenant_id, session_id),
        fetch_all=False,
    )
    flash("Task removed.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


@work_bp.route("/sessions/<int:session_id>/expenses", methods=["POST"])
@login_required
@rate_limit("60 per minute")
def session_add_expense(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if not _can_edit_session(sess):
        flash("You cannot add expenses to this session.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    amount = _optional_decimal(request.form.get("amount", ""))
    if amount is None or amount <= 0:
        flash("Enter a valid expense amount greater than zero.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    desc = sanitize_input(request.form.get("description", "").strip(), max_length=500)
    execute_query(
        """
        INSERT INTO work_expense_items (tenant_id, session_id, amount, description, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            current_user.tenant_id,
            session_id,
            amount,
            desc,
            datetime.utcnow(),
            datetime.utcnow(),
        ),
        fetch_all=False,
    )
    _recompute_session_expenses_from_lines(current_user.tenant_id, session_id)
    flash("Expense line added. Session expense total was updated to match line items.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


@work_bp.route("/sessions/<int:session_id>/income", methods=["POST"])
@login_required
@rate_limit("60 per minute")
def session_add_income(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if not _can_edit_session(sess):
        flash("You cannot add income lines to this session.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    amount = _optional_decimal(request.form.get("amount", ""))
    if amount is None or amount <= 0:
        flash("Enter a valid income amount greater than zero.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    desc = sanitize_input(request.form.get("description", "").strip(), max_length=500)
    execute_query(
        """
        INSERT INTO work_income_items (tenant_id, session_id, amount, description, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            current_user.tenant_id,
            session_id,
            amount,
            desc,
            datetime.utcnow(),
            datetime.utcnow(),
        ),
        fetch_all=False,
    )
    _recompute_session_income_from_lines(current_user.tenant_id, session_id)
    flash("Income line added. Session income total was updated to match line items.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


@work_bp.route("/sessions/<int:session_id>/income/<int:income_id>/delete", methods=["POST"])
@login_required
@rate_limit("60 per minute")
def session_delete_income(session_id: int, income_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if not _can_edit_session(sess):
        flash("You cannot modify income on this session.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    row = execute_query(
        """
        SELECT id, stripe_charge_id FROM work_income_items
        WHERE id = %s AND tenant_id = %s AND session_id = %s
        LIMIT 1
        """,
        (income_id, current_user.tenant_id, session_id),
        fetch_one=True,
    )
    if not row:
        flash("Income line not found.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    charge_id = (row.get("stripe_charge_id") or "").strip()
    execute_query(
        """
        DELETE FROM work_income_items
        WHERE id = %s AND tenant_id = %s AND session_id = %s
        """,
        (income_id, current_user.tenant_id, session_id),
        fetch_all=False,
    )
    if charge_id:
        execute_query(
            """
            DELETE FROM work_expense_items
            WHERE tenant_id = %s AND session_id = %s AND stripe_charge_id = %s
            """,
            (current_user.tenant_id, session_id, charge_id),
            fetch_all=False,
        )
        _recompute_session_expenses_from_lines(current_user.tenant_id, session_id)
    _recompute_session_income_from_lines(current_user.tenant_id, session_id)
    flash("Income line removed.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


@work_bp.route("/sessions/<int:session_id>/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
@rate_limit("60 per minute")
def session_delete_expense(session_id: int, expense_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if not _can_edit_session(sess):
        flash("You cannot modify expenses on this session.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    row = execute_query(
        """
        SELECT id FROM work_expense_items
        WHERE id = %s AND tenant_id = %s AND session_id = %s
        LIMIT 1
        """,
        (expense_id, current_user.tenant_id, session_id),
        fetch_one=True,
    )
    if not row:
        flash("Expense line not found.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    execute_query(
        """
        DELETE FROM work_expense_items
        WHERE id = %s AND tenant_id = %s AND session_id = %s
        """,
        (expense_id, current_user.tenant_id, session_id),
        fetch_all=False,
    )
    _recompute_session_expenses_from_lines(current_user.tenant_id, session_id)
    flash("Expense line removed.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


@work_bp.route("/sessions/<int:session_id>/edit", methods=["GET", "POST"])
@login_required
@rate_limit("60 per minute")
def session_edit(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if not _can_edit_session(sess):
        flash("You cannot edit this session.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))

    tid = current_user.tenant_id
    has_inc = _session_has_income_lines(tid, session_id)
    has_exp = _session_has_expense_lines(tid, session_id)

    def _edit_render_ctx():
        return {
            "session": sess,
            "income_lines_total": _session_income_lines_sum(tid, session_id),
            "expense_lines_total": _session_expense_lines_sum(tid, session_id),
        }

    edit_ctx = _edit_render_ctx()

    if request.method == "POST":
        project = sanitize_input(request.form.get("project", "").strip(), max_length=200)
        if not project:
            flash("Project is required.", "error")
            return render_template("work/session_edit.html", **edit_ctx)
        work_date = _parse_date(request.form.get("work_date", ""))
        if not work_date:
            flash("Work date is required.", "error")
            return render_template("work/session_edit.html", **edit_ctx)
        start_time = _parse_time(request.form.get("start_time", ""))
        if not start_time:
            flash("Start time is required.", "error")
            return render_template("work/session_edit.html", **edit_ctx)
        end_time = _parse_time(request.form.get("end_time", ""))
        notes = sanitize_input(request.form.get("notes", ""), max_length=8000)
        hours_worked = _optional_decimal(request.form.get("hours_worked", ""))
        if hours_worked is not None:
            if hours_worked < 0:
                flash("Hours must be zero or positive.", "error")
                return render_template("work/session_edit.html", **edit_ctx)
            end_time = _end_time_from_start_plus_hours(work_date, start_time, hours_worked)
        elif end_time:
            hours_worked = _hours_from_times(work_date, start_time, end_time)

        prev_end = sess.get("end_time")
        ended_by_user_id = sess.get("ended_by_user_id")
        if end_time is None:
            ended_by_user_id = None
        elif prev_end is None:
            ended_by_user_id = current_user.id

        execute_query(
            """
            UPDATE work_sessions
            SET project = %s, work_date = %s, start_time = %s, end_time = %s,
                hours_worked = %s, notes = %s,
                ended_by_user_id = %s, updated_at = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                project,
                work_date,
                start_time,
                end_time,
                hours_worked,
                notes,
                ended_by_user_id,
                datetime.utcnow(),
                session_id,
                tid,
            ),
            fetch_all=False,
        )
        if has_inc:
            _recompute_session_income_from_lines(tid, session_id)
        if has_exp:
            _recompute_session_expenses_from_lines(tid, session_id)
        flash("Session updated.", "success")
        return redirect(url_for("work.session_detail", session_id=session_id))

    return render_template("work/session_edit.html", **edit_ctx)


@work_bp.route("/reports")
@login_required
def reports():
    month_start, default_to = _report_date_defaults()
    mode = (request.args.get("mode") or "generic").strip().lower()
    if mode not in ("generic", "ei"):
        mode = "generic"
    default_from = month_start if mode == "ei" else _report_generic_default_from()
    date_from = _parse_date(request.args.get("date_from", "")) or default_from
    date_to = _parse_date(request.args.get("date_to", "")) or default_to
    if date_from > date_to:
        flash("Start date must be on or before end date.", "warning")
        default_from = month_start if mode == "ei" else _report_generic_default_from()
        date_from, date_to = default_from, default_to
    project_filter = sanitize_input(request.args.get("project", "").strip(), max_length=200)
    tid = current_user.tenant_id
    rows = _fetch_report_rows(tid, date_from, date_to, project_filter)
    totals = _fetch_report_totals(tid, date_from, date_to, project_filter)
    hours_sum = totals.get("hours_sum") or Decimal("0")
    income_sum = totals.get("income_sum") or Decimal("0")
    expenses_sum = totals.get("expenses_sum") or Decimal("0")
    net = income_sum - expenses_sum
    ei_weekly = (
        _ei_weekly_summary(tid, date_from, date_to, project_filter)
        if mode == "ei"
        else None
    )
    return render_template(
        "work/reports.html",
        mode=mode,
        date_from=date_from,
        date_to=date_to,
        project_filter=project_filter,
        rows=rows,
        hours_sum=hours_sum,
        income_sum=income_sum,
        expenses_sum=expenses_sum,
        net=net,
        ei_weekly=ei_weekly,
    )


def _reports_pdf_cell_str(v, max_len: int = 600) -> str:
    if v is None:
        return "-"
    t = str(v).replace("\r", " ").replace("\n", " ")
    if len(t) > max_len:
        t = t[: max_len - 3] + "..."
    return t.encode("latin-1", "xmlcharrefreplace").decode("latin-1")


def _reports_pdf_created_str(created) -> str:
    if created is None:
        return "-"
    if hasattr(created, "isoformat"):
        return _reports_pdf_cell_str(
            created.isoformat(sep=" ", timespec="seconds"),
            max_len=64,
        )
    return _reports_pdf_cell_str(created, max_len=64)


def _reports_pdf_build_story(
    report_kind: str,
    date_from: date,
    date_to: date,
    project_filter: str,
    rows: list,
    totals: dict,
    ei_weekly: list | None = None,
) -> list:
    styles = getSampleStyleSheet()
    title_txt = (
        "Work report (generic)"
        if report_kind == "generic"
        else "Self-employment / EI summary"
    )
    story = [
        Paragraph(escape(title_txt), styles["Title"]),
        Spacer(1, 8),
        Paragraph(escape(f"Range: {date_from} through {date_to}"), styles["Normal"]),
    ]
    if project_filter:
        story.append(
            Paragraph(
                escape(f"Project filter (contains): {project_filter}"),
                styles["Normal"],
            )
        )
    story.append(Spacer(1, 16))

    hours_sum = totals.get("hours_sum") or Decimal("0")
    income_sum = totals.get("income_sum") or Decimal("0")
    expenses_sum = totals.get("expenses_sum") or Decimal("0")
    net = (totals.get("income_sum") or Decimal("0")) - (totals.get("expenses_sum") or Decimal("0"))

    if report_kind == "ei" and ei_weekly:
        story.append(
            Paragraph(
                escape("Weekly summary"),
                styles["Heading2"],
            )
        )
        story.append(Spacer(1, 6))
        wdata = [
            [
                "Week (Sunday)",
                "Hours worked",
                "Gross self-employment revenue",
            ]
        ]
        for wk in ei_weekly:
            wdata.append(
                [
                    str(wk["week_sunday"]),
                    str(wk["hours"]),
                    str(wk["gross_income"]),
                ]
            )
        wtbl = Table(wdata, repeatRows=1, colWidths=[120, 120, 240])
        wtbl.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(wtbl)
        story.append(Spacer(1, 20))

    if report_kind == "ei":
        summary_labels = ["Hours worked (range)", "Gross self-employment revenue (range)"]
        summary_vals = [str(hours_sum), str(income_sum)]
    else:
        summary_labels = [
            "Total hours",
            "Total income",
            "Total expenses",
            "Net (income - expenses)",
        ]
        summary_vals = [str(hours_sum), str(income_sum), str(expenses_sum), str(net)]
    n_sum = len(summary_labels)
    summary_table = Table(
        [[summary_labels[i], summary_vals[i]] for i in range(n_sum)],
        colWidths=[240, 140],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(Paragraph(escape("Summary"), styles["Heading2"]))
    story.append(Spacer(1, 6))
    story.append(summary_table)
    story.append(Spacer(1, 20))

    if report_kind == "ei":
        hdr = [
            "id",
            "project",
            "work date",
            "start",
            "end",
            "hours",
            "gross income",
            "notes",
            "created",
        ]
        data = [hdr]
        for r in rows:
            data.append(
                [
                    _reports_pdf_cell_str(r.get("id"), max_len=20),
                    _reports_pdf_cell_str(r.get("project"), max_len=100),
                    _reports_pdf_cell_str(r.get("work_date")),
                    _reports_pdf_cell_str(r.get("start_time")),
                    _reports_pdf_cell_str(r.get("end_time")),
                    _reports_pdf_cell_str(r.get("hours_worked")),
                    _reports_pdf_cell_str(r.get("income")),
                    _reports_pdf_cell_str(r.get("notes"), max_len=480),
                    _reports_pdf_created_str(r.get("created_at")),
                ]
            )
        col_widths = [32, 100, 56, 44, 44, 40, 52, 174, 118]
    else:
        hdr = [
            "id",
            "project",
            "work date",
            "start",
            "end",
            "hours",
            "income",
            "expenses",
            "notes",
            "created",
        ]
        data = [hdr]
        for r in rows:
            data.append(
                [
                    _reports_pdf_cell_str(r.get("id"), max_len=20),
                    _reports_pdf_cell_str(r.get("project"), max_len=100),
                    _reports_pdf_cell_str(r.get("work_date")),
                    _reports_pdf_cell_str(r.get("start_time")),
                    _reports_pdf_cell_str(r.get("end_time")),
                    _reports_pdf_cell_str(r.get("hours_worked")),
                    _reports_pdf_cell_str(r.get("income")),
                    _reports_pdf_cell_str(r.get("expenses")),
                    _reports_pdf_cell_str(r.get("notes"), max_len=400),
                    _reports_pdf_created_str(r.get("created_at")),
                ]
            )
        col_widths = [32, 100, 56, 44, 44, 40, 48, 48, 126, 110]

    tbl = Table(data, repeatRows=1, colWidths=col_widths)
    tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(Paragraph(escape("Sessions in range"), styles["Heading2"]))
    story.append(Spacer(1, 6))
    story.append(tbl)
    return story


@work_bp.route("/reports/export.csv")
@login_required
def reports_export_csv():
    month_start, default_to = _report_date_defaults()
    project_filter = sanitize_input(request.args.get("project", "").strip(), max_length=200)
    report_kind = (request.args.get("kind") or "generic").strip().lower()
    if report_kind not in ("generic", "ei"):
        report_kind = "generic"
    default_from = month_start if report_kind == "ei" else _report_generic_default_from()
    date_from = _parse_date(request.args.get("date_from", "")) or default_from
    date_to = _parse_date(request.args.get("date_to", "")) or default_to
    if date_from > date_to:
        default_from = month_start if report_kind == "ei" else _report_generic_default_from()
        date_from, date_to = default_from, default_to
    tid = current_user.tenant_id
    rows = _fetch_report_rows(tid, date_from, date_to, project_filter)
    totals = _fetch_report_totals(tid, date_from, date_to, project_filter)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "Report",
            "generic work summary" if report_kind == "generic" else "EI-oriented self-employment export",
        ]
    )
    w.writerow(["date_from", str(date_from), "date_to", str(date_to)])
    if project_filter:
        w.writerow(["project_filter", project_filter])
    w.writerow([])
    if report_kind == "ei":
        w.writerow(
            [
                "total_hours",
                str(totals.get("hours_sum") or 0),
                "total_gross_self_employment_income",
                str(totals.get("income_sum") or 0),
            ]
        )
    else:
        w.writerow(
            [
                "total_hours",
                str(totals.get("hours_sum") or 0),
                "total_income",
                str(totals.get("income_sum") or 0),
                "total_expenses",
                str(totals.get("expenses_sum") or 0),
                "net_income",
                str(
                    (totals.get("income_sum") or Decimal("0"))
                    - (totals.get("expenses_sum") or Decimal("0"))
                ),
            ]
        )
    w.writerow([])
    if report_kind == "ei":
        ei_weekly_csv = _ei_weekly_summary(tid, date_from, date_to, project_filter)
        w.writerow(["weekly_summary_sun_sat_weeks"])
        w.writerow(
            [
                "week_sunday",
                "hours_worked",
                "gross_self_employment_income",
            ]
        )
        for wk in ei_weekly_csv:
            w.writerow([wk["week_sunday"], wk["hours"], wk["gross_income"]])
        w.writerow([])
        detail_header = [
            "id",
            "project",
            "work_date",
            "start_time",
            "end_time",
            "hours_worked",
            "gross_self_employment_income",
            "notes",
            "created_at",
        ]
    else:
        detail_header = [
            "id",
            "project",
            "work_date",
            "start_time",
            "end_time",
            "hours_worked",
            "income",
            "expenses",
            "notes",
            "created_at",
        ]
    w.writerow(detail_header)
    for r in rows:
        created = r.get("created_at")
        if created is not None and hasattr(created, "isoformat"):
            created_cell = created.isoformat(sep=" ", timespec="seconds")
        else:
            created_cell = created if created is None else str(created)
        notes_cell = (r.get("notes") or "").replace("\n", " ").replace("\r", " ")[:2000]
        if report_kind == "ei":
            w.writerow(
                [
                    r.get("id"),
                    r.get("project"),
                    r.get("work_date"),
                    r.get("start_time"),
                    r.get("end_time"),
                    r.get("hours_worked"),
                    r.get("income"),
                    notes_cell,
                    created_cell,
                ]
            )
        else:
            w.writerow(
                [
                    r.get("id"),
                    r.get("project"),
                    r.get("work_date"),
                    r.get("start_time"),
                    r.get("end_time"),
                    r.get("hours_worked"),
                    r.get("income"),
                    r.get("expenses"),
                    notes_cell,
                    created_cell,
                ]
            )

    filename = f"work-report-{report_kind}-{date_from}-to-{date_to}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@work_bp.route("/reports/export.pdf")
@login_required
@rate_limit("30 per minute")
def reports_export_pdf():
    month_start, default_to = _report_date_defaults()
    project_filter = sanitize_input(request.args.get("project", "").strip(), max_length=200)
    report_kind = (request.args.get("kind") or "generic").strip().lower()
    if report_kind not in ("generic", "ei"):
        report_kind = "generic"
    default_from = month_start if report_kind == "ei" else _report_generic_default_from()
    date_from = _parse_date(request.args.get("date_from", "")) or default_from
    date_to = _parse_date(request.args.get("date_to", "")) or default_to
    if date_from > date_to:
        default_from = month_start if report_kind == "ei" else _report_generic_default_from()
        date_from, date_to = default_from, default_to
    tid = current_user.tenant_id
    rows = _fetch_report_rows(tid, date_from, date_to, project_filter)
    totals = _fetch_report_totals(tid, date_from, date_to, project_filter)
    ei_weekly_pdf = (
        _ei_weekly_summary(tid, date_from, date_to, project_filter)
        if report_kind == "ei"
        else None
    )
    story = _reports_pdf_build_story(
        report_kind,
        date_from,
        date_to,
        project_filter,
        rows,
        totals,
        ei_weekly_pdf,
    )
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(letter),
        leftMargin=36,
        rightMargin=36,
        topMargin=42,
        bottomMargin=42,
        title="Work report",
    )
    doc.build(story)
    pdf_bytes = buf.getvalue()
    filename = f"work-report-{report_kind}-{date_from}-to-{date_to}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _send_tenant_invite_email(to_email: str, tenant_name: str, invite_url: str) -> bool:
    app_name = os.environ.get("APP_NAME", "Web App")
    return send_template_email(
        to_email=to_email,
        subject=f"Team invitation — {tenant_name} ({app_name})",
        template_name="emails/tenant_invite.html",
        template_vars={
            "app_name": app_name,
            "tenant_name": tenant_name,
            "invite_url": invite_url,
        },
    )


@work_bp.route("/team", methods=["GET", "POST"])
@login_required
@rate_limit("30 per minute")
def team_invites():
    if not current_user.is_admin:
        flash("Only team administrators can manage invitations.", "error")
        return redirect(url_for("work.sessions_list"))

    tenant_row = execute_query(
        "SELECT name FROM tenants WHERE id = %s LIMIT 1",
        (current_user.tenant_id,),
        fetch_one=True,
    )
    tenant_name = (tenant_row or {}).get("name") or "Your team"
    utcnow = datetime.utcnow()

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        ok, msg, plain_token = create_invite(
            current_user.tenant_id, email, current_user.id
        )
        if ok and plain_token:
            invite_url = url_for(
                "auth.accept_team_invite", token=plain_token, _external=True
            )
            sent = _send_tenant_invite_email(email, tenant_name, invite_url)
            if sent:
                flash(msg + " An email was sent with the link.", "success")
            else:
                flash(
                    msg
                    + " Email could not be sent; copy the link from logs or try again after configuring mail.",
                    "warning",
                )
        else:
            flash(msg, "error")
        return redirect(url_for("work.team_invites"))

    invites = list_invites_for_tenant(current_user.tenant_id)
    return render_template(
        "work/team_invites.html",
        tenant_name=tenant_name,
        invites=invites,
        utcnow=utcnow,
    )


@work_bp.route("/team/revoke/<int:invite_id>", methods=["POST"])
@login_required
@rate_limit("30 per minute")
def team_invite_revoke(invite_id: int):
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for("work.sessions_list"))
    ok, msg = revoke_invite(current_user.tenant_id, invite_id, current_user.id)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("work.team_invites"))


def _tenant_sessions_for_import(tenant_id: int) -> list:
    rows = execute_query(
        """
        SELECT id, project, work_date, hours_worked, end_time
        FROM work_sessions
        WHERE tenant_id = %s
        ORDER BY work_date DESC, id DESC
        LIMIT 500
        """,
        (tenant_id,),
        fetch_all=True,
    )
    return rows or []


def _tenant_stripe_income_rows(tenant_id: int) -> list:
    rows = execute_query(
        """
        SELECT id, session_id, amount, fee_amount, stripe_charge_id, statement_descriptor
        FROM work_income_items
        WHERE tenant_id = %s
          AND (stripe_charge_id IS NOT NULL OR statement_descriptor IS NOT NULL)
        ORDER BY id DESC
        LIMIT 2000
        """,
        (tenant_id,),
        fetch_all=True,
    )
    return rows or []


def _tenant_stripe_expense_rows(tenant_id: int) -> list:
    rows = execute_query(
        """
        SELECT id, session_id, amount, stripe_charge_id, description, source
        FROM work_expense_items
        WHERE tenant_id = %s
          AND stripe_charge_id IS NOT NULL
          AND btrim(stripe_charge_id) <> ''
        ORDER BY id DESC
        LIMIT 2000
        """,
        (tenant_id,),
        fetch_all=True,
    )
    return rows or []


def _apply_stripe_balance_fee_row(
    tenant_id: int,
    user_id: int,
    payment: dict,
    session_id: int | None,
    create_session: bool,
) -> tuple[bool, str, int | None]:
    """Insert or update an expense-only Stripe balance fee (txn_…)."""
    txn_id = sanitize_input((payment.get("stripe_txn_id") or payment.get("stripe_charge_id") or "").strip(), max_length=200)
    if not txn_id:
        return False, "Missing transaction id.", None

    try:
        expense = Decimal(str(payment.get("expense_amount") or payment.get("fee_amount") or "").strip()).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, ValueError):
        return False, f"{txn_id}: invalid expense amount.", None
    if expense <= 0:
        return False, f"{txn_id}: expense must be positive.", None

    work_date = _parse_date(payment.get("work_date", ""))
    if not work_date:
        return False, f"{txn_id}: invalid work date.", None

    project_hint = sanitize_input(
        (payment.get("project") or payment.get("statement_descriptor") or DEFAULT_BALANCE_FEE_PROJECT).strip(),
        max_length=200,
    ) or DEFAULT_BALANCE_FEE_PROJECT
    project = _canonical_project_name(tenant_id, project_hint)
    description = sanitize_input(
        (payment.get("description") or "").strip() or f"Stripe fee {txn_id}",
        max_length=500,
    )
    now = datetime.utcnow()

    target_session_id = session_id
    if create_session or not target_session_id:
        new_id = _create_import_session(tenant_id, user_id, project, work_date)
        if not new_id:
            return False, f"{txn_id}: could not create session.", None
        target_session_id = new_id
    else:
        sess = _get_session(tenant_id, target_session_id)
        if not sess:
            return False, f"{txn_id}: session not found.", None
        if not _can_edit_session(sess):
            return False, f"{txn_id}: cannot edit that session.", None

    existing = execute_query(
        """
        SELECT id, session_id FROM work_expense_items
        WHERE tenant_id = %s AND stripe_charge_id = %s
        LIMIT 1
        """,
        (tenant_id, txn_id),
        fetch_one=True,
    )
    if existing:
        old_session = int(existing["session_id"])
        execute_query(
            """
            UPDATE work_expense_items
            SET amount = %s, description = %s, source = %s,
                session_id = %s, updated_at = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                expense,
                description,
                "stripe_balance_csv",
                target_session_id,
                now,
                int(existing["id"]),
                tenant_id,
            ),
            fetch_all=False,
        )
        for sid in {old_session, target_session_id}:
            _recompute_session_expenses_from_lines(tenant_id, sid)
        return True, f"{txn_id}: updated", target_session_id

    execute_query(
        """
        INSERT INTO work_expense_items (
            tenant_id, session_id, amount, description,
            stripe_charge_id, source, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            tenant_id,
            target_session_id,
            expense,
            description,
            txn_id,
            "stripe_balance_csv",
            now,
            now,
        ),
        fetch_all=False,
    )
    _recompute_session_expenses_from_lines(tenant_id, target_session_id)
    return True, f"{txn_id}: added", target_session_id


def _canonical_project_name(tenant_id: int, descriptor: str) -> str:
    """
    Prefer an existing work_sessions.project casing that matches the Stripe
    statement descriptor (casefold + whitespace). Falls back to descriptor.
    """
    raw = (descriptor or "").strip()
    if not raw:
        return "Stripe payment"
    norm = normalize_descriptor(raw)
    if not norm:
        return raw
    rows = execute_query(
        """
        SELECT project
        FROM work_sessions
        WHERE tenant_id = %s AND btrim(project) <> ''
        ORDER BY work_date DESC, id DESC
        LIMIT 500
        """,
        (tenant_id,),
        fetch_all=True,
    )
    for row in rows or []:
        project = (row.get("project") or "").strip()
        if project and normalize_descriptor(project) == norm:
            return project
    return raw


def _create_import_session(
    tenant_id: int,
    user_id: int,
    project: str,
    work_date: date,
) -> int | None:
    """Closed zero-hour session for Stripe payments with no matching session."""
    midnight = time_type(0, 0)
    now = datetime.utcnow()
    row = execute_query(
        """
        INSERT INTO work_sessions (
            tenant_id, user_id, project, work_date, start_time, end_time,
            hours_worked, notes, income, expenses, ended_by_user_id, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id,
            user_id,
            project,
            work_date,
            midnight,
            midnight,
            Decimal("0.00"),
            "Created from Stripe CSV import",
            user_id,
            now,
            now,
        ),
        fetch_one=True,
    )
    return int(row["id"]) if row else None


def _apply_stripe_payment_row(
    tenant_id: int,
    user_id: int,
    payment: dict,
    session_id: int | None,
    create_session: bool,
) -> tuple[bool, str, int | None]:
    """
    Insert or update income (gross) + expense (fee) for one Stripe charge.
    Returns (ok, message, session_id).
    """
    charge_id = sanitize_input((payment.get("stripe_charge_id") or "").strip(), max_length=200)
    if not charge_id:
        return False, "Missing charge id.", None

    try:
        gross = Decimal(str(payment.get("gross_amount", "")).strip()).quantize(Decimal("0.01"))
        fee = Decimal(str(payment.get("fee_amount", "0")).strip() or "0").quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return False, f"{charge_id}: invalid amounts.", None

    if gross <= 0:
        return False, f"{charge_id}: gross must be positive.", None
    if fee < 0:
        fee = Decimal("0.00")

    work_date = _parse_date(payment.get("work_date", ""))
    if not work_date:
        return False, f"{charge_id}: invalid work date.", None

    descriptor = sanitize_input(
        (payment.get("statement_descriptor") or "").strip(),
        max_length=200,
    )
    project = _canonical_project_name(tenant_id, descriptor)
    description = sanitize_input(
        (payment.get("description") or "").strip() or f"Stripe {charge_id}",
        max_length=500,
    )
    currency = sanitize_input((payment.get("currency") or "").strip().upper(), max_length=10)
    customer_email = sanitize_input((payment.get("customer_email") or "").strip(), max_length=320)
    stripe_status = sanitize_input(
        (payment.get("stripe_status") or payment.get("status") or "").strip(),
        max_length=80,
    )
    now = datetime.utcnow()

    target_session_id = session_id
    if create_session or not target_session_id:
        new_id = _create_import_session(tenant_id, user_id, project, work_date)
        if not new_id:
            return False, f"{charge_id}: could not create session.", None
        target_session_id = new_id
    else:
        sess = _get_session(tenant_id, target_session_id)
        if not sess:
            return False, f"{charge_id}: session not found.", None
        if not _can_edit_session(sess):
            return False, f"{charge_id}: cannot edit that session.", None

    existing = execute_query(
        """
        SELECT id, session_id FROM work_income_items
        WHERE tenant_id = %s AND stripe_charge_id = %s
        LIMIT 1
        """,
        (tenant_id, charge_id),
        fetch_one=True,
    )

    if existing:
        income_session = int(existing["session_id"])
        execute_query(
            """
            UPDATE work_income_items
            SET amount = %s, fee_amount = %s, description = %s,
                statement_descriptor = %s, currency = %s, customer_email = %s,
                stripe_status = %s, source = %s, updated_at = %s,
                session_id = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                gross,
                fee,
                description,
                descriptor,
                currency,
                customer_email,
                stripe_status,
                "stripe_csv",
                now,
                target_session_id,
                int(existing["id"]),
                tenant_id,
            ),
            fetch_all=False,
        )
        fee_desc = sanitize_input(f"Stripe fee ({charge_id})", max_length=500)
        exp = execute_query(
            """
            SELECT id, session_id FROM work_expense_items
            WHERE tenant_id = %s AND stripe_charge_id = %s
            LIMIT 1
            """,
            (tenant_id, charge_id),
            fetch_one=True,
        )
        if fee > 0:
            if exp:
                execute_query(
                    """
                    UPDATE work_expense_items
                    SET amount = %s, description = %s, source = %s,
                        session_id = %s, updated_at = %s
                    WHERE id = %s AND tenant_id = %s
                    """,
                    (
                        fee,
                        fee_desc,
                        "stripe_csv",
                        target_session_id,
                        now,
                        int(exp["id"]),
                        tenant_id,
                    ),
                    fetch_all=False,
                )
            else:
                execute_query(
                    """
                    INSERT INTO work_expense_items (
                        tenant_id, session_id, amount, description,
                        stripe_charge_id, source, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id,
                        target_session_id,
                        fee,
                        fee_desc,
                        charge_id,
                        "stripe_csv",
                        now,
                        now,
                    ),
                    fetch_all=False,
                )
        elif exp:
            execute_query(
                """
                DELETE FROM work_expense_items
                WHERE id = %s AND tenant_id = %s
                """,
                (int(exp["id"]), tenant_id),
                fetch_all=False,
            )

        sessions_to_fix = {income_session, target_session_id}
        if exp:
            sessions_to_fix.add(int(exp["session_id"]))
        for sid in sessions_to_fix:
            _recompute_session_income_from_lines(tenant_id, sid)
            _recompute_session_expenses_from_lines(tenant_id, sid)
        return True, f"{charge_id}: updated", target_session_id

    execute_query(
        """
        INSERT INTO work_income_items (
            tenant_id, session_id, amount, description, fee_amount,
            stripe_charge_id, statement_descriptor, currency, customer_email,
            stripe_status, source, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            tenant_id,
            target_session_id,
            gross,
            description,
            fee,
            charge_id,
            descriptor,
            currency,
            customer_email,
            stripe_status,
            "stripe_csv",
            now,
            now,
        ),
        fetch_all=False,
    )
    if fee > 0:
        fee_desc = sanitize_input(f"Stripe fee ({charge_id})", max_length=500)
        execute_query(
            """
            INSERT INTO work_expense_items (
                tenant_id, session_id, amount, description,
                stripe_charge_id, source, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                target_session_id,
                fee,
                fee_desc,
                charge_id,
                "stripe_csv",
                now,
                now,
            ),
            fetch_all=False,
        )
    _recompute_session_income_from_lines(tenant_id, target_session_id)
    _recompute_session_expenses_from_lines(tenant_id, target_session_id)
    return True, f"{charge_id}: added", target_session_id


def _read_upload_csv(upload) -> bytes | None:
    """Return CSV bytes or None if empty/missing. Raises ValueError on bad input."""
    if not upload or not getattr(upload, "filename", None):
        return None
    filename = upload.filename.lower()
    if not filename.endswith(".csv"):
        raise ValueError(f"{upload.filename}: upload a .csv file.")
    data = upload.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise ValueError(
            f"{upload.filename}: file too large (max {MAX_CSV_BYTES // (1024 * 1024)} MB)."
        )
    if not data:
        raise ValueError(f"{upload.filename}: empty file.")
    return data


def _refresh_stripe_review(review_rows: list, tid: int) -> list:
    """Rebuild review statuses from the last analyzed payload (payments + fees)."""
    payment_src = [r for r in review_rows if r.get("row_kind") != "balance_fee"]
    fee_src = [r for r in review_rows if r.get("row_kind") == "balance_fee"]
    out: list = []

    if payment_src:
        payments = [
            StripePaymentRow(
                stripe_charge_id=r["stripe_charge_id"],
                created_at_utc=r["created_at_utc"],
                work_date=r["work_date"],
                gross_amount=r["gross_amount"]
                if r.get("gross_amount") not in (None, "—")
                else "0.00",
                fee_amount=r["fee_amount"],
                net_amount=r["net_amount"],
                currency=r.get("currency") or "",
                status=r.get("stripe_status") or "Paid",
                description=r.get("description") or "",
                statement_descriptor=r.get("statement_descriptor") or "",
                customer_email=r.get("customer_email") or "",
                amount_refunded=r.get("amount_refunded") or "0.00",
            )
            for r in payment_src
        ]
        out.extend(
            build_review_rows(
                payments,
                sessions=_tenant_sessions_for_import(tid),
                income_rows=_tenant_stripe_income_rows(tid),
            )
        )

    if fee_src:
        fees = [
            StripeBalanceFeeRow(
                stripe_txn_id=r.get("stripe_txn_id") or r.get("stripe_charge_id") or "",
                created_at_utc=r.get("created_at_utc") or "",
                work_date=r.get("work_date") or "",
                amount=r.get("amount") or "0.00",
                fee=r.get("fee") or "0.00",
                net=r.get("net") or r.get("net_amount") or "0.00",
                expense_amount=r.get("expense_amount") or r.get("fee_amount") or "0.00",
                currency=r.get("currency") or "",
                description=r.get("description") or "",
                txn_type=r.get("txn_type") or r.get("stripe_status") or "stripe_fee",
                project=r.get("project") or DEFAULT_BALANCE_FEE_PROJECT,
            )
            for r in fee_src
        ]
        out.extend(
            build_balance_fee_review_rows(
                fees,
                expense_rows=_tenant_stripe_expense_rows(tid),
            )
        )
    return out


@work_bp.route("/import/stripe", methods=["GET", "POST"])
@login_required
@rate_limit("30 per minute")
def stripe_import():
    """Upload form; POST without analyze action also accepted as analyze alias."""
    if request.method == "POST":
        return stripe_import_analyze()
    flask_session.pop("stripe_import_review", None)
    flask_session.pop("stripe_import_kind", None)
    return render_template(
        "work/stripe_import.html",
        review_rows=None,
        parse_errors=None,
        import_kind=None,
        sessions=_tenant_sessions_for_import(current_user.tenant_id),
    )


@work_bp.route("/import/stripe/analyze", methods=["POST"])
@login_required
@rate_limit("20 per hour")
def stripe_import_analyze():
    payments_upload = request.files.get("payments_csv")
    balance_upload = request.files.get("balance_csv")
    legacy = request.files.get("csv_file")

    try:
        payments_data = _read_upload_csv(payments_upload)
        balance_data = _read_upload_csv(balance_upload)
        if payments_data is None and balance_data is None and legacy and legacy.filename:
            legacy_data = _read_upload_csv(legacy)
            kind = detect_stripe_csv_kind(legacy_data) if legacy_data else None
            if kind == "unified_payments":
                payments_data = legacy_data
            elif kind == "balance_history":
                balance_data = legacy_data
            else:
                flash(
                    "Unrecognized CSV. Export unified payments or balance history from Stripe.",
                    "error",
                )
                return redirect(url_for("work.stripe_import"))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("work.stripe_import"))

    if payments_data is None and balance_data is None:
        flash("Choose at least one CSV (unified payments and/or balance history).", "error")
        return redirect(url_for("work.stripe_import"))

    sessions = _tenant_sessions_for_import(current_user.tenant_id)
    review_rows: list = []
    parse_errors: list[str] = []
    kinds: list[str] = []

    try:
        if payments_data is not None:
            kind = detect_stripe_csv_kind(payments_data)
            if kind != "unified_payments":
                flash(
                    "The payments file does not look like a unified payments CSV.",
                    "error",
                )
                return redirect(url_for("work.stripe_import"))
            payments, errs = parse_unified_payments_csv(payments_data)
            parse_errors.extend(errs)
            if payments:
                review_rows.extend(
                    build_review_rows(
                        payments,
                        sessions=sessions,
                        income_rows=_tenant_stripe_income_rows(current_user.tenant_id),
                    )
                )
                kinds.append("unified_payments")
            else:
                parse_errors.append("Unified payments: no paid positive-amount rows found.")

        if balance_data is not None:
            kind = detect_stripe_csv_kind(balance_data)
            if kind != "balance_history":
                flash(
                    "The balance history file does not look like a Stripe balance history CSV.",
                    "error",
                )
                return redirect(url_for("work.stripe_import"))
            fees, errs = parse_balance_history_csv(balance_data)
            parse_errors.extend(errs)
            if fees:
                review_rows.extend(
                    build_balance_fee_review_rows(
                        fees,
                        expense_rows=_tenant_stripe_expense_rows(current_user.tenant_id),
                    )
                )
                kinds.append("balance_history")
            else:
                parse_errors.append(
                    "Balance history: no stripe_fee rows found (charges are skipped here)."
                )
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("work.stripe_import"))
    except Exception:
        logger.exception("Stripe CSV parse failed")
        flash("Could not read that CSV. Try again with a Stripe export.", "error")
        return redirect(url_for("work.stripe_import"))

    if not review_rows:
        flash("Nothing to import from the uploaded file(s).", "warning")
        return redirect(url_for("work.stripe_import"))

    if len(kinds) == 2:
        import_kind = "combined"
    elif kinds:
        import_kind = kinds[0]
    else:
        import_kind = None

    flask_session["stripe_import_review"] = review_rows
    flask_session["stripe_import_kind"] = import_kind

    return render_template(
        "work/stripe_import.html",
        review_rows=review_rows,
        parse_errors=parse_errors,
        import_kind=import_kind,
        sessions=sessions,
    )


@work_bp.route("/import/stripe/apply", methods=["POST"])
@login_required
@rate_limit("20 per hour")
def stripe_import_apply():
    review_rows = flask_session.get("stripe_import_review") or []
    if not review_rows:
        flash("Nothing to apply. Upload and analyze a CSV first.", "error")
        return redirect(url_for("work.stripe_import"))

    selected = request.form.getlist("row_index")
    if not selected:
        flash("Select at least one row to apply.", "error")
        return render_template(
            "work/stripe_import.html",
            review_rows=review_rows,
            parse_errors=None,
            import_kind=flask_session.get("stripe_import_kind"),
            sessions=_tenant_sessions_for_import(current_user.tenant_id),
        )

    applied = 0
    skipped_matched = 0
    errors: list[str] = []
    tid = current_user.tenant_id
    uid = current_user.id
    created_sessions: dict[tuple[str, str], int] = {}

    for raw_idx in selected:
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(review_rows):
            continue
        row = review_rows[idx]
        if row.get("status") == "matched" and request.form.get(f"force_{idx}") != "1":
            skipped_matched += 1
            continue

        session_choice = (request.form.get(f"session_id_{idx}") or "").strip()
        create_session = session_choice == "__create__" or not session_choice
        session_id = None
        if not create_session:
            try:
                session_id = int(session_choice)
            except ValueError:
                errors.append(f"{row.get('stripe_charge_id')}: invalid session.")
                continue
        else:
            work_date = (row.get("work_date") or "").strip()
            project_norm = (row.get("project_norm") or "").strip()
            group_key = (work_date, project_norm)
            if group_key in created_sessions:
                session_id = created_sessions[group_key]
                create_session = False
            else:
                create_session = True
                session_id = None

        if row.get("row_kind") == "balance_fee":
            ok, msg, used_session_id = _apply_stripe_balance_fee_row(
                tid, uid, row, session_id, create_session
            )
        else:
            ok, msg, used_session_id = _apply_stripe_payment_row(
                tid, uid, row, session_id, create_session
            )
        if ok:
            applied += 1
            if used_session_id and create_session:
                work_date = (row.get("work_date") or "").strip()
                project_norm = (row.get("project_norm") or "").strip()
                created_sessions[(work_date, project_norm)] = int(used_session_id)
        else:
            errors.append(msg)

    log_security_event(
        "stripe_income_import_applied",
        current_user.id,
        {
            "kind": flask_session.get("stripe_import_kind"),
            "applied": applied,
            "skipped_matched": skipped_matched,
            "error_count": len(errors),
        },
    )

    refreshed = _refresh_stripe_review(review_rows, tid)
    flask_session["stripe_import_review"] = refreshed
    sessions = _tenant_sessions_for_import(tid)

    if applied:
        flash(f"Applied {applied} row(s).", "success")
    if skipped_matched:
        flash(f"Skipped {skipped_matched} already-matched row(s).", "info")
    for err in errors[:8]:
        flash(err, "error")
    if len(errors) > 8:
        flash(f"…and {len(errors) - 8} more error(s).", "error")

    return render_template(
        "work/stripe_import.html",
        review_rows=refreshed,
        parse_errors=None,
        import_kind=flask_session.get("stripe_import_kind"),
        sessions=sessions,
    )
