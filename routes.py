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

from database import execute_query
from security import rate_limit, log_security_event, sanitize_input, validate_email
from auth import UserManager
from email_service import send_template_email, send_registration_verified_notice

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
            SELECT id, project, work_date, start_time, end_time, hours_worked, income, expenses
            FROM work_sessions
            WHERE tenant_id = %s
            ORDER BY work_date DESC, id DESC
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
    if not getattr(current_user, "is_site_admin", False):
        flash("Access denied.", "error")
        return redirect(url_for("main.dashboard"))
    stats = {}
    try:
        u = execute_query("SELECT COUNT(*) AS c FROM users", fetch_one=True)
        stats["users"] = int(u["c"]) if u else 0
        t = execute_query("SELECT COUNT(*) AS c FROM tenants", fetch_one=True)
        stats["tenants"] = int(t["c"]) if t else 0
    except Exception as e:
        logger.error("admin stats: %s", e)
        stats = {"users": 0, "tenants": 0}
    return render_template("admin/dashboard.html", stats=stats)


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
