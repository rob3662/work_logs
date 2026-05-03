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
from datetime import date, datetime, time as time_type
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import execute_query
from email_service import send_template_email
from invites import create_invite, list_invites_for_tenant, revoke_invite
from security import log_security_event, rate_limit, sanitize_input

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


def _fetch_report_rows(tenant_id: int, date_from: date, date_to: date, project_filter: str):
    pf = (project_filter or "").strip()
    if pf:
        return execute_query(
            """
            SELECT id, project, work_date, start_time, end_time, hours_worked,
                   income, expenses, notes
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
               income, expenses, notes
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
        SELECT id, amount, description, created_at
        FROM work_expense_items
        WHERE tenant_id = %s AND session_id = %s
        ORDER BY id ASC
        """,
        (tid, session_id),
        fetch_all=True,
    )
    income_items = execute_query(
        """
        SELECT id, amount, description, created_at
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

    end_time = _parse_time(request.form.get("end_time", ""))
    if not end_time:
        flash("End time is required.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))

    hours_override = _optional_decimal(request.form.get("hours_worked", ""))
    work_date = sess["work_date"]
    if isinstance(work_date, str):
        work_date = _parse_date(work_date)
    start_t = sess["start_time"]
    if hours_override is not None and hours_override >= 0:
        hours_worked = hours_override
    else:
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
        SELECT id FROM work_income_items
        WHERE id = %s AND tenant_id = %s AND session_id = %s
        LIMIT 1
        """,
        (income_id, current_user.tenant_id, session_id),
        fetch_one=True,
    )
    if not row:
        flash("Income line not found.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))
    execute_query(
        """
        DELETE FROM work_income_items
        WHERE id = %s AND tenant_id = %s AND session_id = %s
        """,
        (income_id, current_user.tenant_id, session_id),
        fetch_all=False,
    )
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
        if end_time and hours_worked is None:
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
    default_from, default_to = _report_date_defaults()
    date_from = _parse_date(request.args.get("date_from", "")) or default_from
    date_to = _parse_date(request.args.get("date_to", "")) or default_to
    if date_from > date_to:
        flash("Start date must be on or before end date.", "warning")
        date_from, date_to = default_from, default_to
    project_filter = sanitize_input(request.args.get("project", "").strip(), max_length=200)
    mode = (request.args.get("mode") or "generic").strip().lower()
    if mode not in ("generic", "ei"):
        mode = "generic"
    tid = current_user.tenant_id
    rows = _fetch_report_rows(tid, date_from, date_to, project_filter)
    totals = _fetch_report_totals(tid, date_from, date_to, project_filter)
    hours_sum = totals.get("hours_sum") or Decimal("0")
    income_sum = totals.get("income_sum") or Decimal("0")
    expenses_sum = totals.get("expenses_sum") or Decimal("0")
    net = income_sum - expenses_sum
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
    )


@work_bp.route("/reports/export.csv")
@login_required
def reports_export_csv():
    default_from, default_to = _report_date_defaults()
    date_from = _parse_date(request.args.get("date_from", "")) or default_from
    date_to = _parse_date(request.args.get("date_to", "")) or default_to
    if date_from > date_to:
        date_from, date_to = default_from, default_to
    project_filter = sanitize_input(request.args.get("project", "").strip(), max_length=200)
    report_kind = (request.args.get("kind") or "generic").strip().lower()
    if report_kind not in ("generic", "ei"):
        report_kind = "generic"
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
    w.writerow(
        [
            "id",
            "project",
            "work_date",
            "start_time",
            "end_time",
            "hours_worked",
            "income",
            "expenses",
            "notes",
        ]
    )
    for r in rows:
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
                (r.get("notes") or "").replace("\n", " ").replace("\r", " ")[:2000],
            ]
        )

    filename = f"work-report-{report_kind}-{date_from}-to-{date_to}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
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
