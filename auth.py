# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

import os
import secrets
import logging
from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from database import execute_query
from security import validate_password, validate_email, log_security_event

logger = logging.getLogger(__name__)


def is_email_prefix_blocked(email: str) -> bool:
    if not email or "@" not in email:
        return False
    local_part = email.strip().lower().split("@")[0]
    if not local_part:
        return False
    row = execute_query(
        "SELECT 1 FROM blocked_registration_prefixes WHERE prefix = %s",
        (local_part,),
        fetch_one=True,
    )
    return row is not None


def _default_tenant_id() -> int:
    row = execute_query("SELECT id FROM tenants ORDER BY id LIMIT 1", fetch_one=True)
    return int(row["id"]) if row else 1


class User(UserMixin):
    """Flask-Login user loaded from public.users."""

    def __init__(self, user_data):
        self.id = user_data["id"]
        self.tenant_id = user_data.get("tenant_id") or _default_tenant_id()
        self.username = user_data["username"]
        self.email = user_data["email"]
        self.personal_email = user_data.get("personal_email")
        self.password_hash = user_data.get("password_hash")
        self.is_admin = user_data.get("is_admin", False)
        self.is_site_admin = user_data.get("is_site_admin", False)
        self.email_verified = user_data.get("email_verified", False)
        self.personal_email_verified = user_data.get("personal_email_verified", False)
        self.created_at = user_data.get("created_at")
        self.last_login = user_data.get("last_login")

    @property
    def is_active(self):
        return True

    def get_id(self):
        return str(self.id)


class UserManager:
    @staticmethod
    def create_user(username, email, password, is_admin=False, email_verified=False):
        try:
            if username and username.strip().lower() == "admin":
                return False, "The username 'admin' is reserved for the seeded admin account."

            email_valid, email_error = validate_email(email)
            if not email_valid:
                return False, email_error

            if is_email_prefix_blocked(email):
                return False, "Registration is not available for this email address."

            password_valid, password_error = validate_password(password)
            if not password_valid:
                return False, password_error

            email_norm = email.lower().strip()
            dup_email = execute_query(
                """
                SELECT id FROM users WHERE LOWER(TRIM(email)) = %s LIMIT 1
                """,
                (email_norm,),
                fetch_one=True,
            )
            if dup_email:
                return False, "An account with this email already exists."

            dup_username = execute_query(
                """
                SELECT id FROM users WHERE LOWER(TRIM(username)) = %s LIMIT 1
                """,
                (username.strip().lower(),),
                fetch_one=True,
            )
            if dup_username:
                return False, "Username already taken"

            max_users = (os.environ.get("MAX_REGISTERED_USERS") or "").strip()
            if max_users.isdigit():
                cap = int(max_users)
                cnt = execute_query("SELECT COUNT(*) AS c FROM users", fetch_one=True)
                if cnt and int(cnt.get("c") or 0) >= cap:
                    return False, "Registration is closed (user limit reached)."

            tenant_row = execute_query(
                """
                INSERT INTO tenants (name, updated_at)
                VALUES (%s, %s)
                RETURNING id
                """,
                (f"{username.strip()}'s workspace", datetime.utcnow()),
                fetch_one=True,
            )
            if not tenant_row:
                return False, "Failed to create organization"
            tenant_id = int(tenant_row["id"])

            verification_token = secrets.token_urlsafe(32) if not email_verified else None
            password_hash = generate_password_hash(password)

            # is_admin = tenant-level admin (owner or delegate); is_site_admin = global /admin only
            site_admin_flag = False

            result = execute_query(
                """
                INSERT INTO users (
                    tenant_id, username, email, password_hash, is_admin, is_site_admin,
                    email_verified, verification_token, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    tenant_id,
                    username,
                    email_norm,
                    password_hash,
                    is_admin,
                    site_admin_flag,
                    email_verified,
                    verification_token,
                    datetime.utcnow(),
                ),
                fetch_one=True,
            )

            if not result:
                return False, "Failed to create user"

            user_id = result["id"]
            execute_query(
                "UPDATE tenants SET owner_user_id = %s WHERE id = %s",
                (user_id, tenant_id),
                fetch_all=False,
            )
            log_security_event("user_created", user_id, {"email": email})
            payload = {"user_id": user_id, "id": user_id}
            if verification_token:
                payload["verification_token"] = verification_token
            return True, payload

        except Exception as e:
            logger.error("Error creating user: %s", e)
            return False, "An error occurred while creating the user"

    @staticmethod
    def create_user_in_existing_tenant(
        tenant_id: int,
        username: str,
        email: str,
        password: str,
        *,
        is_tenant_admin: bool = False,
        email_verified: bool = True,
    ):
        """Create a user on an existing tenant (e.g. invite acceptance). No new tenant row."""
        try:
            if username and username.strip().lower() == "admin":
                return False, "The username 'admin' is reserved for the seeded admin account."

            email_valid, email_error = validate_email(email)
            if not email_valid:
                return False, email_error

            if is_email_prefix_blocked(email):
                return False, "Registration is not available for this email address."

            password_valid, password_error = validate_password(password)
            if not password_valid:
                return False, password_error

            email_norm = email.lower().strip()
            dup_email = execute_query(
                "SELECT id FROM users WHERE LOWER(TRIM(email)) = %s LIMIT 1",
                (email_norm,),
                fetch_one=True,
            )
            if dup_email:
                return False, "An account with this email already exists."

            dup_username = execute_query(
                """
                SELECT id FROM users WHERE LOWER(TRIM(username)) = %s LIMIT 1
                """,
                (username.strip().lower(),),
                fetch_one=True,
            )
            if dup_username:
                return False, "Username already taken"

            max_users = (os.environ.get("MAX_REGISTERED_USERS") or "").strip()
            if max_users.isdigit():
                cap = int(max_users)
                cnt = execute_query("SELECT COUNT(*) AS c FROM users", fetch_one=True)
                if cnt and int(cnt.get("c") or 0) >= cap:
                    return False, "Registration is closed (user limit reached)."

            tenant_exists = execute_query(
                "SELECT id FROM tenants WHERE id = %s LIMIT 1",
                (tenant_id,),
                fetch_one=True,
            )
            if not tenant_exists:
                return False, "Invalid organization."

            verification_token = None if email_verified else secrets.token_urlsafe(32)
            password_hash = generate_password_hash(password)
            site_admin_flag = False

            result = execute_query(
                """
                INSERT INTO users (
                    tenant_id, username, email, password_hash, is_admin, is_site_admin,
                    email_verified, verification_token, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    tenant_id,
                    username,
                    email_norm,
                    password_hash,
                    is_tenant_admin,
                    site_admin_flag,
                    email_verified,
                    verification_token,
                    datetime.utcnow(),
                ),
                fetch_one=True,
            )

            if not result:
                return False, "Failed to create user"

            user_id = result["id"]
            log_security_event(
                "user_created_invite",
                user_id,
                {"email": email_norm, "tenant_id": tenant_id},
            )
            payload = {"user_id": user_id, "id": user_id}
            if verification_token:
                payload["verification_token"] = verification_token
            return True, payload

        except Exception as e:
            logger.error("Error creating user in tenant: %s", e)
            return False, "An error occurred while creating the user"

    @staticmethod
    def get_user_by_id(user_id):
        try:
            result = execute_query("SELECT * FROM users WHERE id = %s", (user_id,), fetch_one=True)
            return User(result) if result else None
        except Exception as e:
            logger.error("Error getting user by ID: %s", e)
            return None

    @staticmethod
    def get_user_by_email(email):
        try:
            email_lower = email.lower().strip()
            result = execute_query(
                "SELECT * FROM users WHERE email = %s OR personal_email = %s",
                (email_lower, email_lower),
                fetch_one=True,
            )
            return User(result) if result else None
        except Exception as e:
            logger.error("Error getting user by email: %s", e)
            return None

    @staticmethod
    def get_user_by_username(username):
        try:
            result = execute_query(
                "SELECT * FROM users WHERE username = %s", (username,), fetch_one=True
            )
            return User(result) if result else None
        except Exception as e:
            logger.error("Error getting user by username: %s", e)
            return None

    @staticmethod
    def authenticate_user(email, password):
        try:
            user_data = UserManager.get_user_by_email(email)
            if not user_data:
                log_security_event(
                    "login_failed", details={"email": email, "reason": "user_not_found"}
                )
                return None, "Invalid email or password"

            if not check_password_hash(user_data.password_hash, password):
                log_security_event(
                    "login_failed",
                    user_data.id,
                    {"email": email, "reason": "invalid_password"},
                )
                return None, "Invalid email or password"

            UserManager.update_last_login(user_data.id)
            log_security_event("user_login", user_data.id)
            return user_data, "Login successful"

        except Exception as e:
            logger.error("Error authenticating user: %s", e)
            return None, "An error occurred during authentication"

    @staticmethod
    def update_last_login(user_id):
        try:
            execute_query(
                "UPDATE users SET last_login = %s WHERE id = %s RETURNING id",
                (datetime.utcnow(), user_id),
                fetch_one=True,
            )
        except Exception as e:
            logger.error("Error updating last login: %s", e)

    @staticmethod
    def verify_email(user_id, token):
        try:
            user_check = execute_query(
                """
                SELECT id, email_verified FROM users
                WHERE id = %s AND verification_token = %s
                """,
                (user_id, token),
                fetch_one=True,
            )
            if not user_check:
                return False, "Invalid or expired verification token", False
            if user_check.get("email_verified"):
                return True, "Email already verified", False

            execute_query(
                """
                UPDATE users
                SET email_verified = TRUE, verification_token = NULL
                WHERE id = %s AND verification_token = %s
                """,
                (user_id, token),
                fetch_all=False,
            )
            log_security_event("email_verified", user_id)
            return True, "Email verified successfully", True
        except Exception as e:
            logger.error("Error verifying email: %s", e)
            return False, "An error occurred while verifying email", False

    @staticmethod
    def generate_password_reset_token(email):
        try:
            user = UserManager.get_user_by_email(email)
            if not user:
                return False, "User not found"

            reset_token = secrets.token_urlsafe(32)
            expires_at = datetime.utcnow() + timedelta(hours=1)
            execute_query(
                """
                UPDATE users
                SET password_reset_token = %s, password_reset_expires = %s
                WHERE id = %s
                """,
                (reset_token, expires_at, user.id),
                fetch_all=False,
            )
            log_security_event("password_reset_requested", user.id)
            return True, {"reset_token": reset_token, "expires_at": expires_at}
        except Exception as e:
            logger.error("Error generating password reset token: %s", e)
            return False, "An error occurred"

    @staticmethod
    def reset_password(token, new_password):
        try:
            user_row = execute_query(
                """
                SELECT id FROM users
                WHERE password_reset_token = %s
                  AND password_reset_expires > CURRENT_TIMESTAMP
                """,
                (token,),
                fetch_one=True,
            )
            if not user_row:
                return False, "Invalid or expired reset token"

            password_valid, password_error = validate_password(new_password)
            if not password_valid:
                return False, password_error

            new_hash = generate_password_hash(new_password)
            execute_query(
                """
                UPDATE users
                SET password_hash = %s,
                    password_reset_token = NULL,
                    password_reset_expires = NULL
                WHERE id = %s
                """,
                (new_hash, user_row["id"]),
                fetch_all=False,
            )
            log_security_event("password_reset_completed", user_row["id"])
            return True, "Password updated"
        except Exception as e:
            logger.error("Error resetting password: %s", e)
            return False, "An error occurred while resetting password"
