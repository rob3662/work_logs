# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

import os
import logging
import requests
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    flash,
    send_from_directory,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash

from database import execute_query
from security import (
    rate_limit,
    log_security_event,
    sanitize_input,
    validate_email,
    validate_password,
)
from auth import UserManager
from email_service import send_template_email, send_registration_verified_notice
from invites import complete_invite_signup, invite_row_by_token

logger = logging.getLogger(__name__)

RECAPTCHA_SITEVERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def _post_recaptcha_siteverify(secret, recaptcha_response, remote_ip, timeout=8, max_attempts=3):
    data = {"secret": secret, "response": recaptcha_response, "remoteip": remote_ip}
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return requests.post(RECAPTCHA_SITEVERIFY_URL, data=data, timeout=timeout), None
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt + 1 < max_attempts:
                import time

                time.sleep(0.5 * (2**attempt))
    return None, last_exc


def _verify_recaptcha_or_flash():
    recaptcha_secret = os.environ.get("RECAPTCHA_SECRET_KEY") or os.environ.get(
        "RECAPTCHA_PRIVATE_KEY"
    )
    recaptcha_response = request.form.get("g-recaptcha-response", "")
    if not recaptcha_secret:
        flash("reCAPTCHA is not configured. Please try again later.", "error")
        return False
    if not recaptcha_response:
        flash("Please complete the reCAPTCHA challenge.", "error")
        return False
    verify, net_err = _post_recaptcha_siteverify(
        recaptcha_secret, recaptcha_response, request.remote_addr
    )
    if net_err is not None:
        flash(
            "Could not verify reCAPTCHA right now (network). Please try again in a moment.",
            "error",
        )
        return False
    if not verify.ok:
        flash("reCAPTCHA verification failed. Please try again.", "error")
        return False
    vr = verify.json()
    if not vr.get("success"):
        flash("reCAPTCHA verification failed. Please try again.", "error")
        return False
    return True


auth_bp = Blueprint("auth", __name__)
main_bp = Blueprint("main", __name__)
api_bp = Blueprint("api", __name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@auth_bp.route("/register", methods=["GET", "POST"])
@rate_limit("5 per minute")
def register():
    if request.method == "POST":
        if not _verify_recaptcha_or_flash():
            return render_template("auth/register.html")

        username = sanitize_input(request.form.get("username", "").strip())
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or len(username) < 3:
            flash("Username must be at least 3 characters long.", "error")
            return render_template("auth/register.html")

        ok, err = validate_email(email)
        if not ok:
            flash(err, "error")
            return render_template("auth/register.html")

        if not password or len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template("auth/register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("auth/register.html")

        success, result = UserManager.create_user(
            username=username,
            email=email,
            password=password,
            is_admin=True,
            email_verified=False,
        )

        if success:
            user_id = result.get("user_id")
            token = result.get("verification_token")
            if token:
                send_verification_email(email, token, user_id)
                flash(
                    "Registration successful! Check your email to verify your account.",
                    "success",
                )
            else:
                flash("Registered, but verification email could not be queued.", "warning")
            return redirect(url_for("auth.login"))
        flash(result, "error")

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@rate_limit("10 per minute")
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember_me = request.form.get("remember_me") == "on"

        user, message = UserManager.authenticate_user(email, password)
        if user:
            if not user.email_verified:
                flash("Please verify your email before logging in.", "warning")
                return render_template("auth/login.html")
            login_user(user, remember=remember_me)
            nxt = request.args.get("next")
            return redirect(nxt) if nxt else redirect(url_for("main.dashboard"))
        flash(message, "error")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    log_security_event("user_logout", current_user.id)
    from flask_login import logout_user as _lo

    _lo()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/accept-invite/<token>", methods=["GET", "POST"])
@rate_limit("20 per minute")
def accept_team_invite(token):
    inv = invite_row_by_token(token)
    if request.method == "GET":
        if not inv:
            flash("This invitation link is invalid or has expired.", "error")
            return redirect(url_for("auth.login"))
        return render_template("auth/accept_team_invite.html", invite=inv)

    if not inv:
        flash("This invitation link is invalid or has expired.", "error")
        return redirect(url_for("auth.login"))

    username = sanitize_input(request.form.get("username", "").strip())
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not username or len(username) < 3:
        flash("Username must be at least 3 characters long.", "error")
        return render_template("auth/accept_team_invite.html", invite=inv)

    if not password or len(password) < 8:
        flash("Password must be at least 8 characters long.", "error")
        return render_template("auth/accept_team_invite.html", invite=inv)

    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return render_template("auth/accept_team_invite.html", invite=inv)

    ok, msg = complete_invite_signup(token, username, password)
    if ok:
        flash(msg, "success")
        return redirect(url_for("auth.login"))
    flash(msg, "error")
    return render_template("auth/accept_team_invite.html", invite=inv)


@auth_bp.route("/verify/<int:user_id>/<token>")
def verify_email(user_id, token):
    success, message, newly_verified = UserManager.verify_email(user_id, token)
    if success:
        flash(message, "success")
        if newly_verified:
            reg_email = (os.environ.get("REGISTRATION_EMAIL") or "").strip()
            if reg_email:
                user = UserManager.get_user_by_id(user_id)
                if user:
                    send_registration_verified_notice(
                        reg_email,
                        user_id=user.id,
                        username=user.username,
                        user_email=user.email,
                    )
    else:
        flash(message, "error")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@rate_limit("3 per minute")
def forgot_password():
    if request.method == "POST":
        if not _verify_recaptcha_or_flash():
            return render_template("auth/forgot_password.html")

        email = request.form.get("email", "").strip().lower()
        success, result = UserManager.generate_password_reset_token(email)
        if success:
            send_password_reset_email(email, result["reset_token"])
            flash("Password reset instructions sent to your email.", "info")
        else:
            flash(result, "error")

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
@rate_limit("5 per minute")
def reset_password(token):
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template("auth/reset_password.html", token=token)
        success, message = UserManager.reset_password(token, password)
        if success:
            flash("Password reset successfully! You can now log in.", "success")
            return redirect(url_for("auth.login"))
        flash(message, "error")

    return render_template("auth/reset_password.html", token=token)


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    recent_sessions = []
    try:
        recent_sessions = execute_query(
            """
            SELECT ws.id, ws.project, ws.work_date, ws.start_time, ws.end_time,
                   ws.hours_worked, ws.income, ws.expenses,
                   u.username AS started_by_username
            FROM work_sessions ws
            LEFT JOIN users u ON u.id = ws.user_id AND u.tenant_id = ws.tenant_id
            WHERE ws.tenant_id = %s
            ORDER BY ws.work_date DESC, ws.id DESC
            LIMIT 8
            """,
            (current_user.tenant_id,),
            fetch_all=True,
        ) or []
    except Exception as e:
        logger.warning("dashboard work_sessions: %s", e)
    return render_template("dashboard.html", recent_sessions=recent_sessions)


@main_bp.route("/robots.txt")
def robots_txt():
    return send_from_directory(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "robots.txt",
        mimetype="text/plain",
    )


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    pages = [
        "main.index",
        "main.about",
        "main.contact",
        "main.faq",
        "main.privacy_policy",
        "main.terms_of_service",
        "main.disclaimer",
        "main.how_it_works",
    ]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for ep in pages:
        try:
            loc = url_for(ep, _external=True)
            lines.append("<url><loc>%s</loc><changefreq>weekly</changefreq></url>" % loc)
        except Exception:
            continue
    lines.append("</urlset>")
    return "\n".join(lines), 200, {"Content-Type": "application/xml"}


@main_bp.route("/subscription/plans")
def subscription_plans():
    return render_template("subscription/plans.html")


@main_bp.route("/privacy")
def privacy_policy():
    return render_template("legal/privacy_policy.html")


@main_bp.route("/terms")
def terms_of_service():
    return render_template("legal/terms_of_service.html")


@main_bp.route("/disclaimer")
def disclaimer():
    return render_template("legal/disclaimer.html")


@main_bp.route("/contact")
def contact():
    return render_template("legal/contact.html")


@main_bp.route("/about")
def about():
    return render_template("legal/about.html")


@main_bp.route("/faq")
def faq():
    return render_template("legal/faq.html")


@main_bp.route("/how-it-works")
def how_it_works():
    return render_template("legal/how_it_works.html")


@api_bp.route("/healthz")
def healthz():
    return jsonify(
        {
            "success": True,
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    )


@api_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=False)
    sig = request.headers.get("Stripe-Signature", "")
    wh_secret = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    if not wh_secret:
        return jsonify({"success": False, "error": "webhook_not_configured"}), 503
    try:
        import stripe

        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
        stripe.Webhook.construct_event(payload=payload, sig_header=sig, secret=wh_secret)
    except Exception as e:
        logger.warning("Stripe webhook verify failed: %s", e)
        return jsonify({"success": False, "error": "invalid_signature"}), 400
    return jsonify({"success": True, "received": True}), 200


@admin_bp.route("/")
@login_required
def admin_dashboard():
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    stats = {}
    try:
        u = execute_query("SELECT COUNT(*) AS c FROM users", fetch_one=True)
        stats["users"] = int(u["c"]) if u else 0
        t = execute_query("SELECT COUNT(*) AS c FROM tenants", fetch_one=True)
        stats["tenants"] = int(t["c"]) if t else 0
        sa = execute_query(
            "SELECT COUNT(*) AS c FROM users WHERE is_site_admin IS TRUE",
            fetch_one=True,
        )
        stats["site_admins"] = int(sa["c"]) if sa else 0
        orphans = execute_query(
            """
            SELECT COUNT(*) AS c FROM tenants t
            WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.tenant_id = t.id)
            """,
            fetch_one=True,
        )
        stats["orphan_tenants"] = int(orphans["c"]) if orphans else 0
        ev = execute_query("SELECT COUNT(*) AS c FROM security_events", fetch_one=True)
        stats["security_events"] = int(ev["c"]) if ev else 0
    except Exception as e:
        logger.error("admin stats: %s", e)
        stats = {
            "users": 0,
            "tenants": 0,
            "site_admins": 0,
            "orphan_tenants": 0,
            "security_events": 0,
        }
    return render_template("admin/dashboard.html", stats=stats)


def _require_site_admin() -> bool:
    if not getattr(current_user, "is_site_admin", False):
        flash("Access denied.", "error")
        log_security_event(
            "unauthorized_admin_access",
            current_user.id if current_user.is_authenticated else None,
        )
        return False
    return True


def _admin_tenants_options():
    return (
        execute_query(
            """
            SELECT id, name
            FROM tenants
            ORDER BY LOWER(name) ASC, id ASC
            """,
            fetch_all=True,
        )
        or []
    )


def _count_site_admins() -> int:
    row = execute_query(
        "SELECT COUNT(*) AS c FROM users WHERE is_site_admin IS TRUE",
        fetch_one=True,
    )
    return int(row["c"]) if row else 0


@admin_bp.route("/users")
@login_required
@rate_limit("60 per minute")
def admin_users():
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    q = sanitize_input((request.args.get("q") or "").strip(), max_length=200)
    params: list = []
    where = ""
    if q:
        where = """
            WHERE u.username ILIKE %s
               OR u.email ILIKE %s
               OR t.name ILIKE %s
        """
        like = f"%{q}%"
        params.extend([like, like, like])
    users = (
        execute_query(
            f"""
            SELECT u.id, u.username, u.email, u.tenant_id, u.is_admin, u.is_site_admin,
                   u.email_verified, u.last_login, u.created_at,
                   t.name AS tenant_name
            FROM users u
            LEFT JOIN tenants t ON t.id = u.tenant_id
            {where}
            ORDER BY u.id ASC
            LIMIT 500
            """,
            tuple(params) if params else None,
            fetch_all=True,
        )
        or []
    )
    return render_template("admin/users.html", users=users, q=q)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@login_required
@rate_limit("30 per minute")
def admin_user_new():
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    tenants = _admin_tenants_options()
    if request.method == "POST":
        username = sanitize_input((request.form.get("username") or "").strip(), max_length=80)
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        tenant_mode = (request.form.get("tenant_mode") or "existing").strip()
        tenant_id_raw = (request.form.get("tenant_id") or "").strip()
        new_tenant_name = sanitize_input(
            (request.form.get("new_tenant_name") or "").strip(), max_length=200
        )
        is_tenant_admin = request.form.get("is_admin") == "1"
        is_site_admin = request.form.get("is_site_admin") == "1"
        email_verified = request.form.get("email_verified") == "1"

        if not username or not email or not password:
            flash("Username, email, and password are required.", "error")
            return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")

        email_ok, email_err = validate_email(email)
        if not email_ok:
            flash(email_err, "error")
            return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")
        pw_ok, pw_err = validate_password(password)
        if not pw_ok:
            flash(pw_err, "error")
            return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")

        if username.strip().lower() == "admin" and not is_site_admin:
            flash("The username 'admin' is reserved.", "error")
            return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")

        email_norm = email.lower().strip()
        if execute_query(
            "SELECT id FROM users WHERE LOWER(TRIM(email)) = %s LIMIT 1",
            (email_norm,),
            fetch_one=True,
        ):
            flash("An account with this email already exists.", "error")
            return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")
        if execute_query(
            "SELECT id FROM users WHERE LOWER(TRIM(username)) = %s LIMIT 1",
            (username.strip().lower(),),
            fetch_one=True,
        ):
            flash("Username already taken.", "error")
            return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")

        now = datetime.utcnow()
        if tenant_mode == "new":
            tname = new_tenant_name or f"{username}'s workspace"
            trow = execute_query(
                """
                INSERT INTO tenants (name, created_at, updated_at)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (tname, now, now),
                fetch_one=True,
            )
            if not trow:
                flash("Could not create tenant.", "error")
                return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")
            tenant_id = int(trow["id"])
            is_tenant_admin = True
        else:
            try:
                tenant_id = int(tenant_id_raw)
            except (TypeError, ValueError):
                flash("Select a tenant.", "error")
                return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")
            if not execute_query(
                "SELECT id FROM tenants WHERE id = %s LIMIT 1",
                (tenant_id,),
                fetch_one=True,
            ):
                flash("Tenant not found.", "error")
                return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")

        row = execute_query(
            """
            INSERT INTO users (
                tenant_id, username, email, password_hash, is_admin, is_site_admin,
                email_verified, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                username,
                email_norm,
                generate_password_hash(password),
                is_tenant_admin,
                is_site_admin,
                email_verified,
                now,
                now,
            ),
            fetch_one=True,
        )
        if not row:
            flash("Could not create user.", "error")
            return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")

        user_id = int(row["id"])
        if tenant_mode == "new":
            execute_query(
                "UPDATE tenants SET owner_user_id = %s, updated_at = %s WHERE id = %s",
                (user_id, now, tenant_id),
                fetch_all=False,
            )
        log_security_event(
            "admin_user_created",
            current_user.id,
            {"user_id": user_id, "tenant_id": tenant_id, "is_site_admin": is_site_admin},
        )
        flash(f"User #{user_id} created.", "success")
        return redirect(url_for("admin.admin_users"))

    return render_template("admin/user_form.html", user=None, tenants=tenants, mode="new")


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@rate_limit("30 per minute")
def admin_user_edit(user_id: int):
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    user = execute_query(
        """
        SELECT u.*, t.name AS tenant_name
        FROM users u
        LEFT JOIN tenants t ON t.id = u.tenant_id
        WHERE u.id = %s
        LIMIT 1
        """,
        (user_id,),
        fetch_one=True,
    )
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.admin_users"))
    tenants = _admin_tenants_options()

    if request.method == "POST":
        username = sanitize_input((request.form.get("username") or "").strip(), max_length=80)
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        try:
            tenant_id = int(request.form.get("tenant_id") or user["tenant_id"])
        except (TypeError, ValueError):
            flash("Invalid tenant.", "error")
            return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")
        is_tenant_admin = request.form.get("is_admin") == "1"
        is_site_admin = request.form.get("is_site_admin") == "1"
        email_verified = request.form.get("email_verified") == "1"

        if not username or not email:
            flash("Username and email are required.", "error")
            return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")
        email_ok, email_err = validate_email(email)
        if not email_ok:
            flash(email_err, "error")
            return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")
        if password:
            pw_ok, pw_err = validate_password(password)
            if not pw_ok:
                flash(pw_err, "error")
                return render_template(
                    "admin/user_form.html", user=user, tenants=tenants, mode="edit"
                )

        if int(user_id) == int(current_user.id) and not is_site_admin:
            flash("You cannot remove your own site admin flag.", "error")
            return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")

        if user.get("is_site_admin") and not is_site_admin and _count_site_admins() <= 1:
            flash("Cannot remove the last site admin.", "error")
            return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")

        if not execute_query(
            "SELECT id FROM tenants WHERE id = %s LIMIT 1",
            (tenant_id,),
            fetch_one=True,
        ):
            flash("Tenant not found.", "error")
            return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")

        email_norm = email.lower().strip()
        dup = execute_query(
            """
            SELECT id FROM users
            WHERE LOWER(TRIM(email)) = %s AND id <> %s
            LIMIT 1
            """,
            (email_norm, user_id),
            fetch_one=True,
        )
        if dup:
            flash("Another account already uses that email.", "error")
            return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")
        dup_u = execute_query(
            """
            SELECT id FROM users
            WHERE LOWER(TRIM(username)) = %s AND id <> %s
            LIMIT 1
            """,
            (username.strip().lower(), user_id),
            fetch_one=True,
        )
        if dup_u:
            flash("Another account already uses that username.", "error")
            return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")

        now = datetime.utcnow()
        if password:
            execute_query(
                """
                UPDATE users SET
                    username = %s, email = %s, tenant_id = %s,
                    is_admin = %s, is_site_admin = %s, email_verified = %s,
                    password_hash = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    username,
                    email_norm,
                    tenant_id,
                    is_tenant_admin,
                    is_site_admin,
                    email_verified,
                    generate_password_hash(password),
                    now,
                    user_id,
                ),
                fetch_all=False,
            )
        else:
            execute_query(
                """
                UPDATE users SET
                    username = %s, email = %s, tenant_id = %s,
                    is_admin = %s, is_site_admin = %s, email_verified = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    username,
                    email_norm,
                    tenant_id,
                    is_tenant_admin,
                    is_site_admin,
                    email_verified,
                    now,
                    user_id,
                ),
                fetch_all=False,
            )
        log_security_event(
            "admin_user_updated",
            current_user.id,
            {"user_id": user_id, "tenant_id": tenant_id},
        )
        flash("User updated.", "success")
        return redirect(url_for("admin.admin_users"))

    return render_template("admin/user_form.html", user=user, tenants=tenants, mode="edit")


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@rate_limit("30 per minute")
def admin_user_delete(user_id: int):
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    if int(user_id) == int(current_user.id):
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.admin_users"))
    user = execute_query(
        "SELECT id, is_site_admin, username FROM users WHERE id = %s LIMIT 1",
        (user_id,),
        fetch_one=True,
    )
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.admin_users"))
    if user.get("is_site_admin") and _count_site_admins() <= 1:
        flash("Cannot delete the last site admin.", "error")
        return redirect(url_for("admin.admin_users"))
    execute_query("DELETE FROM users WHERE id = %s", (user_id,), fetch_all=False)
    log_security_event(
        "admin_user_deleted",
        current_user.id,
        {"user_id": user_id, "username": user.get("username")},
    )
    flash("User deleted.", "success")
    return redirect(url_for("admin.admin_users"))


@admin_bp.route("/users/<int:user_id>/send-reset", methods=["POST"])
@login_required
@rate_limit("10 per minute")
def admin_user_send_reset(user_id: int):
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    user = execute_query(
        "SELECT id, email, username FROM users WHERE id = %s LIMIT 1",
        (user_id,),
        fetch_one=True,
    )
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.admin_users"))
    email = (user.get("email") or "").strip().lower()
    success, result = UserManager.generate_password_reset_token(email)
    if not success:
        flash(result if isinstance(result, str) else "Could not create reset token.", "error")
        return redirect(url_for("admin.admin_user_edit", user_id=user_id))
    send_password_reset_email(email, result["reset_token"])
    log_security_event(
        "admin_password_reset_sent",
        current_user.id,
        {"target_user_id": user_id, "email": email},
    )
    flash(f"Password reset email sent to {email}.", "success")
    return redirect(url_for("admin.admin_user_edit", user_id=user_id))


@admin_bp.route("/security-events")
@login_required
@rate_limit("60 per minute")
def admin_security_events():
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    q = sanitize_input((request.args.get("q") or "").strip(), max_length=200)
    params: list = []
    where = ""
    if q:
        where = """
            WHERE se.event_type ILIKE %s
               OR CAST(se.details AS TEXT) ILIKE %s
               OR u.username ILIKE %s
               OR u.email ILIKE %s
        """
        like = f"%{q}%"
        params.extend([like, like, like, like])
    events = (
        execute_query(
            f"""
            SELECT se.id, se.event_type, se.user_id, se.ip_address, se.user_agent,
                   se.details, se.created_at,
                   u.username, u.email
            FROM security_events se
            LEFT JOIN users u ON u.id = se.user_id
            {where}
            ORDER BY se.id DESC
            LIMIT 200
            """,
            tuple(params) if params else None,
            fetch_all=True,
        )
        or []
    )
    total_row = execute_query("SELECT COUNT(*) AS c FROM security_events", fetch_one=True)
    total_count = int(total_row["c"]) if total_row else 0
    return render_template(
        "admin/security_events.html",
        events=events,
        q=q,
        total_count=total_count,
    )


@admin_bp.route("/security-events/delete", methods=["POST"])
@login_required
@rate_limit("10 per minute")
def admin_security_events_delete():
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    action = (request.form.get("action") or "").strip().casefold()
    confirm = (request.form.get("confirm") or "").strip().casefold()

    if action == "clear_all":
        if confirm != "delete events":
            flash('Type "delete events" to confirm clearing the log.', "error")
            return redirect(url_for("admin.admin_security_events"))
        deleted_rows = (
            execute_query(
                "DELETE FROM security_events RETURNING id",
                fetch_all=True,
            )
            or []
        )
        deleted = len(deleted_rows)
        log_security_event(
            "admin_security_events_cleared",
            current_user.id,
            {"deleted": deleted},
        )
        flash(f"Cleared {deleted} security event(s).", "success")
        return redirect(url_for("admin.admin_security_events"))

    if action == "delete_selected":
        raw_ids = request.form.getlist("event_ids")
        ids: list[int] = []
        for raw in raw_ids:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        # Cap batch size to the page limit
        ids = ids[:200]
        if not ids:
            flash("Select at least one event to delete.", "error")
            return redirect(url_for("admin.admin_security_events"))
        placeholders = ", ".join(["%s"] * len(ids))
        deleted_rows = (
            execute_query(
                f"DELETE FROM security_events WHERE id IN ({placeholders}) RETURNING id",
                tuple(ids),
                fetch_all=True,
            )
            or []
        )
        deleted = len(deleted_rows)
        log_security_event(
            "admin_security_events_deleted",
            current_user.id,
            {"deleted": deleted, "ids": [int(r["id"]) for r in deleted_rows]},
        )
        flash(f"Deleted {deleted} security event(s).", "success")
        q = sanitize_input((request.form.get("q") or "").strip(), max_length=200)
        return redirect(url_for("admin.admin_security_events", q=q or None))

    flash("Unknown delete action.", "error")
    return redirect(url_for("admin.admin_security_events"))


@admin_bp.route("/tenants")
@login_required
@rate_limit("60 per minute")
def admin_tenants():
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    q = sanitize_input((request.args.get("q") or "").strip(), max_length=200)
    orphans_only = (request.args.get("orphans") or "").strip() == "1"
    params: list = []
    clauses: list[str] = []
    if q:
        clauses.append("t.name ILIKE %s")
        params.append(f"%{q}%")
    if orphans_only:
        clauses.append("NOT EXISTS (SELECT 1 FROM users u2 WHERE u2.tenant_id = t.id)")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    tenants = (
        execute_query(
            f"""
            SELECT t.id, t.name, t.owner_user_id, t.created_at, t.updated_at,
                   (SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.id) AS user_count,
                   ou.username AS owner_username
            FROM tenants t
            LEFT JOIN users ou ON ou.id = t.owner_user_id
            {where}
            ORDER BY t.id ASC
            LIMIT 500
            """,
            tuple(params) if params else None,
            fetch_all=True,
        )
        or []
    )
    orphan_count_row = execute_query(
        """
        SELECT COUNT(*) AS c FROM tenants t
        WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.tenant_id = t.id)
        """,
        fetch_one=True,
    )
    orphan_count = int(orphan_count_row["c"]) if orphan_count_row else 0
    return render_template(
        "admin/tenants.html",
        tenants=tenants,
        q=q,
        orphans_only=orphans_only,
        orphan_count=orphan_count,
    )


@admin_bp.route("/tenants/cleanup-orphans", methods=["POST"])
@login_required
@rate_limit("10 per minute")
def admin_tenants_cleanup_orphans():
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    confirm = (request.form.get("confirm") or "").strip().casefold()
    if confirm != "delete orphans":
        flash('Type "delete orphans" to confirm cleanup.', "error")
        return redirect(url_for("admin.admin_tenants", orphans="1"))
    rows = (
        execute_query(
            """
            SELECT id, name FROM tenants t
            WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.tenant_id = t.id)
              AND t.id <> %s
            """,
            (current_user.tenant_id,),
            fetch_all=True,
        )
        or []
    )
    deleted = 0
    for row in rows:
        execute_query("DELETE FROM tenants WHERE id = %s", (int(row["id"]),), fetch_all=False)
        deleted += 1
    log_security_event(
        "admin_orphan_tenants_deleted",
        current_user.id,
        {"deleted": deleted, "ids": [int(r["id"]) for r in rows]},
    )
    flash(f"Deleted {deleted} orphan tenant(s).", "success")
    return redirect(url_for("admin.admin_tenants"))


@admin_bp.route("/tenants/new", methods=["GET", "POST"])
@login_required
@rate_limit("30 per minute")
def admin_tenant_new():
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        name = sanitize_input((request.form.get("name") or "").strip(), max_length=200)
        if not name:
            flash("Tenant name is required.", "error")
            return render_template("admin/tenant_form.html", tenant=None, users=[], mode="new")
        now = datetime.utcnow()
        row = execute_query(
            """
            INSERT INTO tenants (name, created_at, updated_at)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (name, now, now),
            fetch_one=True,
        )
        if not row:
            flash("Could not create tenant.", "error")
            return render_template("admin/tenant_form.html", tenant=None, users=[], mode="new")
        log_security_event(
            "admin_tenant_created",
            current_user.id,
            {"tenant_id": int(row["id"]), "name": name},
        )
        flash(f"Tenant #{row['id']} created. Add users and assign them to it.", "success")
        return redirect(url_for("admin.admin_tenants"))
    return render_template("admin/tenant_form.html", tenant=None, users=[], mode="new")


@admin_bp.route("/tenants/<int:tenant_id>/edit", methods=["GET", "POST"])
@login_required
@rate_limit("30 per minute")
def admin_tenant_edit(tenant_id: int):
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    tenant = execute_query(
        "SELECT * FROM tenants WHERE id = %s LIMIT 1",
        (tenant_id,),
        fetch_one=True,
    )
    if not tenant:
        flash("Tenant not found.", "error")
        return redirect(url_for("admin.admin_tenants"))
    users = (
        execute_query(
            """
            SELECT id, username, email, is_admin
            FROM users WHERE tenant_id = %s
            ORDER BY username ASC
            """,
            (tenant_id,),
            fetch_all=True,
        )
        or []
    )
    if request.method == "POST":
        name = sanitize_input((request.form.get("name") or "").strip(), max_length=200)
        owner_raw = (request.form.get("owner_user_id") or "").strip()
        if not name:
            flash("Tenant name is required.", "error")
            return render_template(
                "admin/tenant_form.html", tenant=tenant, users=users, mode="edit"
            )
        owner_user_id = None
        if owner_raw:
            try:
                owner_user_id = int(owner_raw)
            except ValueError:
                flash("Invalid owner.", "error")
                return render_template(
                    "admin/tenant_form.html", tenant=tenant, users=users, mode="edit"
                )
            if not any(int(u["id"]) == owner_user_id for u in users):
                flash("Owner must be a user on this tenant.", "error")
                return render_template(
                    "admin/tenant_form.html", tenant=tenant, users=users, mode="edit"
                )
        execute_query(
            """
            UPDATE tenants SET name = %s, owner_user_id = %s, updated_at = %s
            WHERE id = %s
            """,
            (name, owner_user_id, datetime.utcnow(), tenant_id),
            fetch_all=False,
        )
        log_security_event(
            "admin_tenant_updated",
            current_user.id,
            {"tenant_id": tenant_id, "name": name},
        )
        flash("Tenant updated.", "success")
        return redirect(url_for("admin.admin_tenants"))
    return render_template("admin/tenant_form.html", tenant=tenant, users=users, mode="edit")


@admin_bp.route("/tenants/<int:tenant_id>/delete", methods=["POST"])
@login_required
@rate_limit("20 per minute")
def admin_tenant_delete(tenant_id: int):
    if not _require_site_admin():
        return redirect(url_for("main.dashboard"))
    if int(current_user.tenant_id) == int(tenant_id):
        flash("You cannot delete the tenant you are currently signed into.", "error")
        return redirect(url_for("admin.admin_tenants"))
    tenant = execute_query(
        "SELECT id, name FROM tenants WHERE id = %s LIMIT 1",
        (tenant_id,),
        fetch_one=True,
    )
    if not tenant:
        flash("Tenant not found.", "error")
        return redirect(url_for("admin.admin_tenants"))
    confirm = (request.form.get("confirm_name") or "").strip()
    if confirm != (tenant.get("name") or ""):
        flash("Type the tenant name exactly to confirm deletion.", "error")
        return redirect(url_for("admin.admin_tenant_edit", tenant_id=tenant_id))
    # CASCADE removes users and work data for this tenant
    execute_query("DELETE FROM tenants WHERE id = %s", (tenant_id,), fetch_all=False)
    log_security_event(
        "admin_tenant_deleted",
        current_user.id,
        {"tenant_id": tenant_id, "name": tenant.get("name")},
    )
    flash("Tenant and all of its users/data were deleted.", "success")
    return redirect(url_for("admin.admin_tenants"))


def send_verification_email(email, token, user_id):
    try:
        app_name = os.environ.get("APP_NAME", "Web App")
        verify_url = url_for("auth.verify_email", user_id=user_id, token=token, _external=True)
        send_template_email(
            to_email=email,
            subject=f"Verify your email — {app_name}",
            template_name="emails/verify_email.html",
            template_vars={"token": token, "user_id": user_id, "verify_url": verify_url, "app_name": app_name},
        )
    except Exception as e:
        logger.error("send_verification_email: %s", e)


def send_password_reset_email(email, token):
    try:
        app_name = os.environ.get("APP_NAME", "Web App")
        reset_url = url_for("auth.reset_password", token=token, _external=True)
        send_template_email(
            to_email=email,
            subject=f"Reset your password — {app_name}",
            template_name="emails/reset_password.html",
            template_vars={"token": token, "reset_url": reset_url, "app_name": app_name},
        )
    except Exception as e:
        logger.error("send_password_reset_email: %s", e)
