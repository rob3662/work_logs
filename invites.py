# === LICENSE HEADER START ===
# Copyright (c) 2026 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

"""Tenant invitation tokens and acceptance (single-tenant users; new email only)."""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta

from database import execute_query
from security import validate_email, validate_password, log_security_event

logger = logging.getLogger(__name__)


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _invite_ttl_days() -> int:
    raw = (os.environ.get("TENANT_INVITE_EXPIRES_DAYS") or "7").strip()
    try:
        n = int(raw)
        return max(1, min(n, 90))
    except ValueError:
        return 7


def invite_row_by_token(raw_token: str):
    """Return invite row joined with tenant name if token valid and still usable."""
    if not raw_token or len(raw_token) < 20:
        return None
    th = _token_hash(raw_token.strip())
    row = execute_query(
        """
        SELECT ti.*, t.name AS tenant_name
        FROM tenant_invites ti
        JOIN tenants t ON t.id = ti.tenant_id
        WHERE ti.token_hash = %s
          AND ti.accepted_at IS NULL
          AND ti.revoked_at IS NULL
          AND ti.expires_at > CURRENT_TIMESTAMP
        LIMIT 1
        """,
        (th,),
        fetch_one=True,
    )
    return row


def list_invites_for_tenant(tenant_id: int):
    return execute_query(
        """
        SELECT id, email, created_at, expires_at, accepted_at, revoked_at,
               invited_by_user_id
        FROM tenant_invites
        WHERE tenant_id = %s
        ORDER BY created_at DESC
        LIMIT 100
        """,
        (tenant_id,),
        fetch_all=True,
    ) or []


def create_invite(tenant_id: int, email: str, invited_by_user_id: int) -> tuple[bool, str, str | None]:
    """
    Create a pending invite. Returns (success, message, plain_token_or_none).
    Plain token is returned only for embedding in the invitation email.
    """
    ok, err = validate_email(email)
    if not ok:
        return False, err, None

    email_norm = email.lower().strip()

    from auth import is_email_prefix_blocked

    if is_email_prefix_blocked(email_norm):
        return False, "Invites are not allowed for this email address.", None

    existing = execute_query(
        """
        SELECT id FROM users WHERE LOWER(TRIM(email)) = %s LIMIT 1
        """,
        (email_norm,),
        fetch_one=True,
    )
    if existing:
        return (
            False,
            "That email already has an account. Invites are only for new users; use a different address or remove the other account first.",
            None,
        )

    member = execute_query(
        """
        SELECT id FROM users WHERE tenant_id = %s AND LOWER(TRIM(email)) = %s LIMIT 1
        """,
        (tenant_id, email_norm),
        fetch_one=True,
    )
    if member:
        return False, "That address is already a member of this team.", None

    execute_query(
        """
        UPDATE tenant_invites
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE tenant_id = %s
          AND LOWER(TRIM(email)) = %s
          AND accepted_at IS NULL
          AND revoked_at IS NULL
        """,
        (tenant_id, email_norm),
        fetch_all=False,
    )

    raw = secrets.token_urlsafe(32)
    th = _token_hash(raw)
    expires_at = datetime.utcnow() + timedelta(days=_invite_ttl_days())

    try:
        execute_query(
            """
            INSERT INTO tenant_invites (
                tenant_id, email, token_hash, invited_by_user_id,
                created_at, expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                email_norm,
                th,
                invited_by_user_id,
                datetime.utcnow(),
                expires_at,
            ),
            fetch_all=False,
        )
    except Exception as e:
        logger.error("create_invite insert failed: %s", e)
        err = str(e).lower()
        if "unique" in err or "duplicate" in err:
            return (
                False,
                "An invitation is already pending for this email. Revoke it first or wait until it expires.",
                None,
            )
        return False, "Could not create invite (try again).", None

    log_security_event(
        "tenant_invite_created",
        invited_by_user_id,
        {"tenant_id": tenant_id, "email": email_norm},
    )
    return True, "Invite created.", raw


def revoke_invite(tenant_id: int, invite_id: int, acting_user_id: int) -> tuple[bool, str]:
    row = execute_query(
        """
        SELECT id FROM tenant_invites
        WHERE id = %s AND tenant_id = %s
          AND accepted_at IS NULL AND revoked_at IS NULL
        LIMIT 1
        """,
        (invite_id, tenant_id),
        fetch_one=True,
    )
    if not row:
        return False, "Invite not found or already used."
    execute_query(
        """
        UPDATE tenant_invites
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE id = %s AND tenant_id = %s
        """,
        (invite_id, tenant_id),
        fetch_all=False,
    )
    log_security_event(
        "tenant_invite_revoked",
        acting_user_id,
        {"tenant_id": tenant_id, "invite_id": invite_id},
    )
    return True, "Invite revoked."


def complete_invite_signup(raw_token: str, username: str, password: str) -> tuple[bool, str]:
    """Validate token and create user on invite tenant. Email is taken from the invite."""
    from auth import UserManager

    inv = invite_row_by_token(raw_token)
    if not inv:
        return False, "This invite link is invalid or has expired."

    email_norm = (inv.get("email") or "").lower().strip()
    tenant_id = int(inv["tenant_id"])
    invite_id = int(inv["id"])

    ok, result = UserManager.create_user_in_existing_tenant(
        tenant_id=tenant_id,
        username=username,
        email=email_norm,
        password=password,
        is_tenant_admin=False,
        email_verified=True,
    )
    if not ok:
        return False, (result if isinstance(result, str) else "Could not create account.")

    user_id = result.get("user_id") or result.get("id")
    execute_query(
        """
        UPDATE tenant_invites
        SET accepted_at = CURRENT_TIMESTAMP
        WHERE id = %s AND tenant_id = %s
        """,
        (invite_id, tenant_id),
        fetch_all=False,
    )
    log_security_event(
        "tenant_invite_accepted",
        user_id,
        {"tenant_id": tenant_id, "invite_id": invite_id, "email": email_norm},
    )
    return True, "Account created. You can sign in now."
