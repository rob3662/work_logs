# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

"""
Email service module: SendGrid API, Mailgun API, or SMTP (e.g. Brevo).
Handles all email sending functionality for the application.
"""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List
from flask import render_template
import requests

logger = logging.getLogger(__name__)


def _default_no_reply() -> str:
    domain = (os.environ.get("DOMAIN_NAME") or "localhost").strip()
    return os.environ.get("NO_REPLY", f"noreply@{domain}")


def send_email_via_smtp(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    from_email: Optional[str] = None
) -> bool:
    """
    Send an email using SMTP (e.g. Brevo, Gmail).
    Uses MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_USE_TLS from environment.
    """
    try:
        server = (os.environ.get('MAIL_SERVER') or '').strip()
        if not server:
            logger.error("MAIL_SERVER not set; cannot send email via SMTP")
            return False
        port = int(os.environ.get('MAIL_PORT', '587'))
        use_tls = (os.environ.get('MAIL_USE_TLS', 'true').lower() in ('true', '1', 'yes'))
        username = (os.environ.get('MAIL_USERNAME') or '').strip()
        password = (os.environ.get('MAIL_PASSWORD') or '').strip()
        if not username or not password:
            logger.error("MAIL_USERNAME and MAIL_PASSWORD must be set for SMTP")
            return False
        if not from_email:
            from_email = _default_no_reply()

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
        plain_body = text_content if text_content else (html_content or '')
        msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        if html_content:
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        if use_tls and port == 587:
            with smtplib.SMTP(server, port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(username, password)
                smtp.sendmail(from_email, [to_email], msg.as_string())
        elif port == 465:
            with smtplib.SMTP_SSL(server, port, timeout=30) as smtp:
                smtp.login(username, password)
                smtp.sendmail(from_email, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(server, port, timeout=30) as smtp:
                if use_tls:
                    smtp.starttls()
                smtp.login(username, password)
                smtp.sendmail(from_email, [to_email], msg.as_string())

        logger.info(f"✅ Email sent via SMTP to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"❌ Error sending email via SMTP: {e}")
        return False

def send_email_via_sendgrid(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    from_email: Optional[str] = None
) -> bool:
    """
    Send an email using SendGrid API
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_content: HTML email content
        text_content: Plain text email content (optional, auto-generated from HTML if not provided)
        from_email: Sender email address (defaults to NO_REPLY from .env)
    
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, Content
        
        # Get SendGrid API key (strip whitespace - 401 often caused by trailing newline in .env)
        api_key = (os.environ.get('SENDGRID_API_KEY') or '').strip()
        if not api_key:
            logger.error("SENDGRID_API_KEY not found in environment variables")
            return False
        
        # Get sender email
        if not from_email:
            from_email = _default_no_reply()
        
        # Initialize SendGrid client
        sg = sendgrid.SendGridAPIClient(api_key=api_key)
        
        # Create email message with to_emails as string
        message = Mail(
            from_email=Email(from_email),
            to_emails=to_email,  # String email address (not Email object)
            subject=subject,
            html_content=Content("text/html", html_content)
        )
        
        # Add plain text content if provided
        if text_content:
            message.add_content(Content("text/plain", text_content))
        
        # Send email
        response = sg.send(message)
        
        if response.status_code in [200, 201, 202]:
            logger.info(f"✅ Email sent successfully to {to_email}: {subject}")
            return True
        else:
            logger.error(f"❌ SendGrid API error: Status {response.status_code}, Body: {response.body}")
            return False
            
    except ImportError:
        logger.error("SendGrid library not installed. Install with: pip install sendgrid")
        return False
    except Exception as e:
        logger.error(f"❌ Error sending email via SendGrid: {e}")
        return False


def send_email_via_mailgun(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    from_email: Optional[str] = None
) -> bool:
    """
    Send an email using Mailgun API.
    Uses MAILGUN_API_KEY and MAILGUN_DOMAIN from environment.
    If MAILGUN_DOMAIN is not set, falls back to the domain portion of NO_REPLY/from_email.

    Optional env:
      MAILGUN_API_BASE - override API host (default US: https://api.mailgun.net)
      MAILGUN_REGION - set to 'eu' to use https://api.eu.mailgun.net (EU accounts require this)
    """
    try:
        api_key = (os.environ.get('MAILGUN_API_KEY') or '').strip().strip('"').strip("'")
        if not api_key:
            logger.error("MAILGUN_API_KEY not found in environment variables")
            return False

        if not from_email:
            from_email = (os.environ.get("NO_REPLY") or "").strip() or _default_no_reply()

        domain = (os.environ.get('MAILGUN_DOMAIN') or '').strip()
        if not domain:
            if '@' in from_email:
                domain = from_email.split('@', 1)[1].strip()
        if not domain:
            logger.error("MAILGUN_DOMAIN not set and unable to infer domain from sender email")
            return False

        # EU accounts get 401 Forbidden if you call the US API. See Mailgun "Base URLs" in docs.
        explicit_base = (os.environ.get('MAILGUN_API_BASE') or '').strip().rstrip('/')
        region = (os.environ.get('MAILGUN_REGION') or '').strip().lower()
        if explicit_base:
            api_bases = [explicit_base]
        elif region == 'eu':
            api_bases = ['https://api.eu.mailgun.net']
        elif region == 'us':
            api_bases = ['https://api.mailgun.net']
        else:
            # Try US first; on 401 only, retry EU (common for new EU-region signups).
            api_bases = ['https://api.mailgun.net', 'https://api.eu.mailgun.net']

        # Mailgun expects form fields; `to` must be a string (not a list) for application/x-www-form-urlencoded.
        payload = {
            'from': from_email,
            'to': to_email,
            'subject': subject,
            'text': text_content if text_content else (html_content or ''),
        }
        if html_content:
            payload['html'] = html_content

        last_response = None
        for idx, api_base in enumerate(api_bases):
            endpoint = f"{api_base}/v3/{domain}/messages"
            response = requests.post(endpoint, auth=('api', api_key), data=payload, timeout=30)
            last_response = response
            if response.status_code in (200, 202):
                logger.info(f"✅ Email sent via Mailgun to {to_email}: {subject}")
                return True
            if response.status_code == 401 and idx + 1 < len(api_bases):
                logger.warning(
                    "Mailgun returned 401 on %s; retrying alternate region endpoint (EU vs US mismatch is common).",
                    api_base,
                )
                continue
            break

        logger.error(f"❌ Mailgun API error: Status {last_response.status_code}, Body: {last_response.text}")
        if last_response.status_code == 401:
            logger.error(
                "Mailgun 401: confirm Private API key (Domain settings > Sending API keys), "
                "MAILGUN_DOMAIN matches Mailgun exactly (e.g. mg.logs.brakesystems.ca), "
                "and set MAILGUN_REGION=eu or MAILGUN_API_BASE=https://api.eu.mailgun.net if your account is EU."
            )
        return False
    except Exception as e:
        logger.error(f"❌ Error sending email via Mailgun: {e}")
        return False

def send_template_email(
    to_email: str,
    subject: str,
    template_name: str,
    template_vars: dict,
    from_email: Optional[str] = None
) -> bool:
    """
    Send an email using a Jinja2 template
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        template_name: Name of the email template (e.g., 'emails/verify_email.html')
        template_vars: Dictionary of variables to pass to the template
        from_email: Sender email address (defaults to NO_REPLY from .env)
    
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        from flask import current_app
        
        with current_app.app_context():
            # Render HTML template
            html_content = render_template(template_name, **template_vars)
            
            # Generate plain text version (simple HTML stripping)
            import re
            text_content = re.sub(r'<[^>]+>', '', html_content)
            text_content = re.sub(r'\n\s*\n', '\n\n', text_content).strip()
            
            # Backend priority: Mailgun -> SendGrid -> SMTP.
            mailgun_api_key = (os.environ.get('MAILGUN_API_KEY') or '').strip()
            if mailgun_api_key:
                return send_email_via_mailgun(
                    to_email=to_email,
                    subject=subject,
                    html_content=html_content,
                    text_content=text_content,
                    from_email=from_email
                )
            sendgrid_api_key = (os.environ.get('SENDGRID_API_KEY') or '').strip()
            if sendgrid_api_key:
                return send_email_via_sendgrid(
                    to_email=to_email,
                    subject=subject,
                    html_content=html_content,
                    text_content=text_content,
                    from_email=from_email
                )
            if (os.environ.get('MAIL_SERVER') or '').strip():
                return send_email_via_smtp(
                    to_email=to_email,
                    subject=subject,
                    html_content=html_content,
                    text_content=text_content,
                    from_email=from_email
                )
            logger.error("No email backend configured: set MAILGUN_API_KEY, or SENDGRID_API_KEY, or MAIL_SERVER (with MAIL_USERNAME/MAIL_PASSWORD)")
            return False
    except Exception as e:
        logger.error(f"❌ Error sending template email: {e}")
        return False


def send_registration_verified_notice(
    registration_email: str,
    *,
    user_id: int,
    username: str,
    user_email: str,
) -> bool:
    """
    Notify REGISTRATION_EMAIL when a user completes work-email verification.

    If registration_email is empty, returns False without sending.
    """
    to_addr = (registration_email or "").strip()
    if not to_addr:
        logger.debug("REGISTRATION_EMAIL not set; skipping registration verified notice")
        return False
    try:
        return send_template_email(
            to_email=to_addr,
            subject=f"{os.environ.get('APP_NAME', 'Web App')}: email verified — {user_email}",
            template_name="emails/registration_verified_notice.html",
            template_vars={
                "user_id": user_id,
                "username": username,
                "user_email": user_email,
            },
        )
    except Exception as e:
        logger.error("Error sending registration verified notice: %s", e)
        return False

