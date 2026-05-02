# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

"""
setup_database.py
Creates minimal multi-tenant tables and applies small idempotent upgrades.
Called once per Gunicorn master (see app/app.py lock) and safe to re-run.
"""

import os
import logging
from datetime import datetime

from dotenv import load_dotenv

from database import execute_query

load_dotenv()
logger = logging.getLogger(__name__)


def _column_exists(table_name: str, column_name: str) -> bool:
    row = execute_query(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        LIMIT 1
        """,
        (table_name, column_name),
        fetch_one=True,
    )
    return row is not None


def _ensure_column(table_name: str, column_name: str, ddl: str) -> None:
    if not _column_exists(table_name, column_name):
        execute_query(ddl, fetch_all=False)
        logger.info("Applied schema change: %s.%s", table_name, column_name)


def init_db() -> None:
    """Create core tables and seed default tenant + admin user."""
    try:
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL DEFAULT 'Default',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            fetch_all=False,
        )

        execute_query(
            """
            CREATE TABLE IF NOT EXISTS blocked_registration_prefixes (
                id SERIAL PRIMARY KEY,
                prefix TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            fetch_all=False,
        )

        execute_query(
            """
            CREATE TABLE IF NOT EXISTS security_events (
                id SERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                user_id INTEGER,
                ip_address TEXT,
                user_agent TEXT,
                details JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            fetch_all=False,
        )

        execute_query(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                email_verified BOOLEAN DEFAULT FALSE,
                verification_token TEXT,
                personal_email TEXT,
                personal_email_verified BOOLEAN DEFAULT FALSE,
                personal_email_verification_token TEXT,
                password_reset_token TEXT,
                password_reset_expires TIMESTAMP,
                stripe_customer_id TEXT,
                last_login TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, username),
                UNIQUE (tenant_id, email)
            );
            """,
            fetch_all=False,
        )

        # Idempotent column adds for existing DBs upgraded from older templates
        _ensure_column(
            "users",
            "tenant_id",
            "ALTER TABLE users ADD COLUMN tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE;",
        )

        row = execute_query("SELECT id FROM tenants ORDER BY id LIMIT 1", fetch_one=True)
        if not row:
            execute_query(
                "INSERT INTO tenants (name) VALUES ('Default')",
                fetch_all=False,
            )
            row = execute_query("SELECT id FROM tenants ORDER BY id LIMIT 1", fetch_one=True)
        default_tenant_id = row["id"] if row else 1

        # Backfill tenant_id for legacy rows (if any)
        execute_query(
            "UPDATE users SET tenant_id = %s WHERE tenant_id IS NULL",
            (default_tenant_id,),
            fetch_all=False,
        )

        admin_user = (os.environ.get("ADMIN_USERNAME_IN_DB") or "admin").strip()
        admin_email = (os.environ.get("ADMIN_EMAIL_IN_DB") or "").strip().lower()
        admin_password = os.environ.get("ADMIN_PASSWORD_IN_DB") or ""

        if admin_email and admin_password:
            from werkzeug.security import generate_password_hash

            exists = execute_query(
                """
                SELECT id FROM users
                WHERE tenant_id = %s AND (LOWER(email) = %s OR LOWER(username) = %s)
                LIMIT 1
                """,
                (default_tenant_id, admin_email, admin_user.lower()),
                fetch_one=True,
            )
            if not exists:
                ph = generate_password_hash(admin_password)
                execute_query(
                    """
                    INSERT INTO users (
                        tenant_id, username, email, password_hash, is_admin, email_verified,
                        verification_token, created_at
                    ) VALUES (%s, %s, %s, %s, TRUE, TRUE, NULL, %s)
                    """,
                    (
                        default_tenant_id,
                        admin_user,
                        admin_email,
                        ph,
                        datetime.utcnow(),
                    ),
                    fetch_all=False,
                )
                logger.info("Seeded admin user %s", admin_user)
        else:
            logger.warning(
                "ADMIN_EMAIL_IN_DB / ADMIN_PASSWORD_IN_DB not set; skipping admin seed"
            )

        logger.info("Database initialization (template) completed")
    except Exception as e:
        logger.error("init_db failed: %s", e)
        raise
