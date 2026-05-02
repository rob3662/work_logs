# === LICENSE HEADER START ===
# Copyright (c) 2026 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

"""Work log routes: tenant-scoped sessions and tasks."""

import logging
from datetime import date, datetime, time as time_type
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import execute_query
from security import rate_limit, sanitize_input

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


@work_bp.route("/sessions")
@login_required
def sessions_list():
    rows = execute_query(
        """
        SELECT id, project, work_date, start_time, end_time, hours_worked, income, expenses, user_id
        FROM work_sessions
        WHERE tenant_id = %s
        ORDER BY work_date DESC, start_time DESC, id DESC
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
        income = _optional_decimal(request.form.get("income", ""))
        expenses = _optional_decimal(request.form.get("expenses", ""))

        row = execute_query(
            """
            INSERT INTO work_sessions (
                tenant_id, user_id, project, work_date, start_time, end_time,
                hours_worked, notes, income, expenses, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, NULL, NULL, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                current_user.tenant_id,
                current_user.id,
                project,
                work_date,
                start_time,
                notes,
                income,
                expenses,
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
    tasks = execute_query(
        """
        SELECT id, task_text, created_at
        FROM work_tasks
        WHERE tenant_id = %s AND session_id = %s
        ORDER BY id ASC
        """,
        (current_user.tenant_id, session_id),
        fetch_all=True,
    )
    return render_template("work/session_detail.html", session=sess, tasks=tasks or [])


@work_bp.route("/sessions/<int:session_id>/stop", methods=["POST"])
@login_required
@rate_limit("60 per minute")
def session_stop(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if sess.get("user_id") != current_user.id and not current_user.is_admin:
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
        SET end_time = %s, hours_worked = %s, updated_at = %s
        WHERE id = %s AND tenant_id = %s
        """,
        (end_time, hours_worked, datetime.utcnow(), session_id, current_user.tenant_id),
        fetch_all=False,
    )
    flash("Session stopped.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


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
        INSERT INTO work_tasks (tenant_id, session_id, task_text, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            current_user.tenant_id,
            session_id,
            text,
            datetime.utcnow(),
            datetime.utcnow(),
        ),
        fetch_all=False,
    )
    flash("Task added.", "success")
    return redirect(url_for("work.session_detail", session_id=session_id))


@work_bp.route("/sessions/<int:session_id>/edit", methods=["GET", "POST"])
@login_required
@rate_limit("60 per minute")
def session_edit(session_id: int):
    sess = _get_session(current_user.tenant_id, session_id)
    if not sess:
        flash("Session not found.", "error")
        return redirect(url_for("work.sessions_list"))
    if sess.get("user_id") != current_user.id and not current_user.is_admin:
        flash("You cannot edit this session.", "error")
        return redirect(url_for("work.session_detail", session_id=session_id))

    if request.method == "POST":
        project = sanitize_input(request.form.get("project", "").strip(), max_length=200)
        if not project:
            flash("Project is required.", "error")
            return render_template("work/session_edit.html", session=sess)
        work_date = _parse_date(request.form.get("work_date", ""))
        if not work_date:
            flash("Work date is required.", "error")
            return render_template("work/session_edit.html", session=sess)
        start_time = _parse_time(request.form.get("start_time", ""))
        if not start_time:
            flash("Start time is required.", "error")
            return render_template("work/session_edit.html", session=sess)
        end_time = _parse_time(request.form.get("end_time", ""))
        notes = sanitize_input(request.form.get("notes", ""), max_length=8000)
        income = _optional_decimal(request.form.get("income", ""))
        expenses = _optional_decimal(request.form.get("expenses", ""))
        hours_worked = _optional_decimal(request.form.get("hours_worked", ""))
        if end_time and hours_worked is None:
            hours_worked = _hours_from_times(work_date, start_time, end_time)

        execute_query(
            """
            UPDATE work_sessions
            SET project = %s, work_date = %s, start_time = %s, end_time = %s,
                hours_worked = %s, notes = %s, income = %s, expenses = %s, updated_at = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                project,
                work_date,
                start_time,
                end_time,
                hours_worked,
                notes,
                income,
                expenses,
                datetime.utcnow(),
                session_id,
                current_user.tenant_id,
            ),
            fetch_all=False,
        )
        flash("Session updated.", "success")
        return redirect(url_for("work.session_detail", session_id=session_id))

    return render_template("work/session_edit.html", session=sess)
