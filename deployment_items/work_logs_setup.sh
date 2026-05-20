#!/bin/bash

# Website Setup Template Script
# Unified setup script for any website deployment on the server
# Handles both development and production environments based on FLASK_ENV in .env file
# Generic website setup script (no domain-specific assumptions).
# init_new_project.sh renames this file to <slug>_setup.sh; update docs/paths accordingly.

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_status() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[-]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[i]${NC} $1"
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKING_DIR="$(dirname "$SCRIPT_DIR")"

# Setup fresh run logging (console + file):
# - deployment_items/logs/setup_latest.log is recreated every run
# - previous latest log is archived with timestamp
LOG_DIR="$SCRIPT_DIR/logs"
LATEST_LOG="$LOG_DIR/setup_latest.log"
mkdir -p "$LOG_DIR"
if [ -f "$LATEST_LOG" ] && [ -s "$LATEST_LOG" ]; then
    mv "$LATEST_LOG" "$LOG_DIR/setup_$(date +"%Y%m%d_%H%M%S").log"
fi
: > "$LATEST_LOG"
exec > >(tee -a "$LATEST_LOG") 2>&1

# Setup logging (fresh file each run)
SETUP_LOG_DIR="${WORKING_DIR}/logs"
SETUP_LOG_FILE="${SETUP_LOG_DIR}/setup_run.log"
mkdir -p "${SETUP_LOG_DIR}"
: > "${SETUP_LOG_FILE}"
exec > >(tee -a "${SETUP_LOG_FILE}") 2>&1

# Get the actual user (not root when running with sudo)
if [ -n "$SUDO_USER" ]; then
    SERVICE_USER="$SUDO_USER"
else
    SERVICE_USER="$(whoami)"
fi

# Configuration variables - UPDATE THESE FOR YOUR WEBSITE
WEBSITE_NAME="work_logs"  # e.g., "math_basics", "workout_tracker", "my_new_site"
WEBSITE_PORT="5054"  # e.g., "5050", "5051", "5052" - must be unique per website
WEBSITE_DOMAIN="logs.brakesystems.ca"  # public domain for this site
GUNICORN_WORKERS="4"  # Number of Gunicorn workers (default: 1, recommended: 2-4 for production)

# Host development venv only — align major.minor with Containerfile (FROM python:3.13-slim).
# Use a concrete interpreter name (Fedora: python3.13 from python3.13 package) or a full path (pyenv, deadsnakes).
# Set DEV_PYTHON_VERSION_EXPECTED= to empty string in this script to skip the exact patch check.
DEV_PYTHON_BIN="${DEV_PYTHON_BIN:-python3.13}"
DEV_PYTHON_VERSION_EXPECTED="${DEV_PYTHON_VERSION_EXPECTED:-3.13.12}"

# Auto-generated from WEBSITE_NAME (no need to change these)
DB_NAME="${WEBSITE_NAME}_db"
DB_USER="${WEBSITE_NAME}_user"
BACKUP_SCRIPT="backup_${WEBSITE_NAME}"

print_status "Website Setup Template Script"
print_status "Working directory: $WORKING_DIR"
print_status "Website: $WEBSITE_NAME"
print_status "Port: $WEBSITE_PORT"
print_status "Domain: $WEBSITE_DOMAIN"

# Function to check if we can run sudo commands
check_sudo() {
    if ! sudo -n true 2>/dev/null; then
        print_warning "This script needs sudo privileges for some operations."
        print_warning "You'll be prompted for your password when needed."
        print_warning "Press Enter to continue..."
        read -r
    fi
}

# Resolves DEV_PYTHON_BIN for development; sets DEV_PYTHON_RESOLVED or exits.
# Honors optional DEV_PYTHON_VERSION_EXPECTED (e.g. 3.13.12) to match the venv to your container image line.
resolve_dev_python() {
    local bin candidate got
    candidate="${DEV_PYTHON_BIN:-python3.13}"
    if command -v "$candidate" >/dev/null 2>&1; then
        bin="$(command -v "$candidate")"
    elif [ -x "$candidate" ]; then
        bin="$candidate"
    else
        bin=""
    fi
    if [ -z "$bin" ]; then
        print_error "Development Python interpreter not found: ${candidate}"
        print_error "Install Python 3.13 for your OS (example Fedora: sudo dnf install python3.13 python3.13-devel),"
        print_error "or set DEV_PYTHON_BIN at the top of this script to a full path (e.g. ~/.pyenv/versions/3.13.12/bin/python)."
        exit 1
    fi
    got="$("$bin" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
    if [ -n "${DEV_PYTHON_VERSION_EXPECTED:-}" ]; then
        if [ "$got" != "$DEV_PYTHON_VERSION_EXPECTED" ]; then
            print_error "Python at $bin is ${got}, but DEV_PYTHON_VERSION_EXPECTED=${DEV_PYTHON_VERSION_EXPECTED}."
            print_error "Install that patch release, point DEV_PYTHON_BIN at the right binary, or clear DEV_PYTHON_VERSION_EXPECTED in this script to skip the check."
            exit 1
        fi
        print_status "Development Python version OK: ${got} (${bin})"
    else
        print_status "Using Python ${got} at ${bin} for development (DEV_PYTHON_VERSION_EXPECTED unset — patch not checked)"
    fi
    DEV_PYTHON_RESOLVED="$bin"
}

# True if SKIP_CLOUDFLARE_TUNNEL is set to 1/true/yes/on (case-insensitive value).
cloudflare_tunnel_skipped_via_env() {
    local env_file="$1"
    local raw
    raw=$(grep '^SKIP_CLOUDFLARE_TUNNEL=' "$env_file" 2>/dev/null | head -n1 | sed 's/^SKIP_CLOUDFLARE_TUNNEL=//' | tr -d ' \t\r"'"'" | tr 'A-Z' 'a-z' || true)
    case "$raw" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

# Returns 0 if .env has non-placeholder Cloudflare tunnel credentials.
cloudflare_tunnel_env_is_configured() {
    local env_file="$1"
    local tid atag sec
    tid=$(grep '^CLOUDFLARE_TUNNEL_ID=' "$env_file" 2>/dev/null | head -n1 | sed 's/^CLOUDFLARE_TUNNEL_ID=//' | tr -d ' \t\r' || true)
    atag=$(grep '^CLOUDFLARE_ACCOUNT_TAG=' "$env_file" 2>/dev/null | head -n1 | sed 's/^CLOUDFLARE_ACCOUNT_TAG=//' | tr -d ' \t\r' || true)
    sec=$(grep '^CLOUDFLARE_TUNNEL_SECRET=' "$env_file" 2>/dev/null | head -n1 | sed 's/^CLOUDFLARE_TUNNEL_SECRET=//' | tr -d '" \t\r' || true)
    [ -z "$tid" ] && return 1
    [ -z "$atag" ] && return 1
    [ -z "$sec" ] && return 1
    [ "$tid" = "your_tunnel_id_here" ] && return 1
    [ "$atag" = "your_account_tag_here" ] && return 1
    [ "$sec" = "your_tunnel_secret_here_in_quotes_because_of_equals_sign" ] && return 1
    return 0
}

cloudflare_tunnel_manual_setup_instructions() {
    local dom="$1"
    print_error "Cloudflare tunnel credentials are missing or still set to placeholders in $WORKING_DIR/.env"
    print_info "Set SKIP_CLOUDFLARE_TUNNEL=true in .env if you intentionally run production without a tunnel."
    print_warning "Create a tunnel and obtain CLOUDFLARE_TUNNEL_ID, CLOUDFLARE_ACCOUNT_TAG, and CLOUDFLARE_TUNNEL_SECRET."
    print_warning "Run as ${SERVICE_USER} on this host (cloudflared must be installed, e.g. from server_bootstrap.sh):"
    print_warning ""
    print_warning "  cloudflared tunnel login        # one-time browser flow; writes ~/.cloudflared/cert.pem"
    print_warning "  cloudflared tunnel create ${WEBSITE_NAME}-tunnel"
    print_warning ""
    print_warning "Then copy TunnelID, AccountTag, and TunnelSecret from ~/.cloudflared/<tunnel-id>.json into .env:"
    print_warning "  CLOUDFLARE_TUNNEL_ID=<TunnelID>"
    print_warning "  CLOUDFLARE_ACCOUNT_TAG=<AccountTag>"
    print_warning "  CLOUDFLARE_TUNNEL_SECRET=\"<TunnelSecret>\""
    print_warning ""
    _apex="${dom#*.}"
    _rel="${dom%.$_apex}"
    print_warning "Re-run this setup script. In the DNS zone for ${_apex}, add a proxied CNAME: name ${_rel}, target <TunnelID>.cfargotunnel.com"
    print_warning ""
}

cloudflare_update_env_tunnel_vars() {
    local env_file="$1" tid="$2" atag="$3" sec="$4"
    local tmp
    tmp=$(mktemp "${env_file}.cf.XXXXXX")
    grep -v '^CLOUDFLARE_TUNNEL_ID=' "$env_file" | grep -v '^CLOUDFLARE_ACCOUNT_TAG=' | grep -v '^CLOUDFLARE_TUNNEL_SECRET=' > "$tmp" || true
    {
        printf 'CLOUDFLARE_TUNNEL_ID=%s\n' "$tid"
        printf 'CLOUDFLARE_ACCOUNT_TAG=%s\n' "$atag"
        printf 'CLOUDFLARE_TUNNEL_SECRET="%s"\n' "$sec"
    } >> "$tmp"
    mv -f "$tmp" "$env_file"
    chmod 600 "$env_file"
    chown "$SERVICE_USER:$SERVICE_USER" "$env_file" 2>/dev/null || true
}

# Check if .env file exists and determine environment
if [ -f "$WORKING_DIR/.env" ]; then
    FLASK_ENV=$(grep "^FLASK_ENV=" "$WORKING_DIR/.env" | cut -d'=' -f2 | tr -d ' ')
    print_status "Found .env file with FLASK_ENV=$FLASK_ENV"
else
    print_warning "No .env file found. Creating template and exiting..."
    print_warning "Please update the .env file with your actual values, then run setup again."
    print_warning "Important variables to update:"
    print_warning "  - FLASK_SECRET_KEY"
    print_warning "  - DB_PASSWORD"
    print_warning "  - SENDGRID_API_KEY (if using email features)"
    print_warning "  - RECAPTCHA_SITE_KEY and RECAPTCHA_SECRET_KEY (if using reCAPTCHA)"
    print_warning "  - Cloudflare configuration (for production use)"

    # Create .env template
    cat > "$WORKING_DIR/.env" << EOF
# Flask Configuration
FLASK_SECRET_KEY=your_secret_key_here_change_this

# Human-readable app name (UI + email subjects)
APP_NAME=My Web App

# Optional: cap self-service registrations (non-admin). Leave unset for unlimited.
# MAX_REGISTERED_USERS=100

# Development Configuration (uncomment for development)
FLASK_ENV=development
FLASK_DEBUG=True
PORT=${WEBSITE_PORT}
HOST=127.0.0.1
LOG_LEVEL=INFO

# Production Configuration (uncomment for production)
# FLASK_ENV=production
# FLASK_DEBUG=False
# PORT=${WEBSITE_PORT}
# HOST=0.0.0.0
# LOG_LEVEL=WARNING

# Static assets cache-busting (bump to force browser reload)
ASSETS_VERSION=1

# Additional security
SESSION_COOKIE_HTTPONLY=True

# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=your_database_password_here

# Redis Configuration (for rate limiting - shared across workers)
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Admin Configuration (if using admin features)
ADMIN_USERNAME_IN_DB=admin
ADMIN_EMAIL_IN_DB=brakesystemsca@gmail.com
ADMIN_PASSWORD_IN_DB=your_admin_password_here

# Email Configuration (SendGrid - Recommended)
# Get your API key from: https://app.sendgrid.com/settings/api_keys
SENDGRID_API_KEY=your_sendgrid_api_key_here
NO_REPLY=noreply@${WEBSITE_DOMAIN}

# Mailgun Configuration (optional, alternative to SendGrid/SMTP)
MAILGUN_API_KEY=your_mailgun_api_key_here
MAILGUN_DOMAIN=mg.${WEBSITE_DOMAIN}
MAILGUN_REGION=us
MAILGUN_API_BASE=https://api.mailgun.net

# SMTP Configuration (used when SENDGRID_API_KEY is empty)
# Recommended: Brevo (free plan, 300 emails/day)
MAIL_SERVER=smtp-relay.brevo.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_DEBUG=False
MAIL_USERNAME=username@smtp-brevo.com
MAIL_PASSWORD=your_brevo_smtp_key_here
MAIL_DEFAULT_SENDER=noreply@${WEBSITE_DOMAIN}

# Contact Email Addresses (customize as needed)
ADMIN_EMAIL=admin@${WEBSITE_DOMAIN}
REGISTRATION_EMAIL=registration@${WEBSITE_DOMAIN}
CONTACT_US_EMAIL=contact@${WEBSITE_DOMAIN}
FEATURES_EMAIL=features@${WEBSITE_DOMAIN}
FEEDBACK_EMAIL=feedback@${WEBSITE_DOMAIN}
PRIVACY_EMAIL=privacy@${WEBSITE_DOMAIN}
SUPPORT_EMAIL=support@${WEBSITE_DOMAIN}
TERMS_EMAIL=terms@${WEBSITE_DOMAIN}

# Email logging
EMAIL_LOG_FILE=logs/email.log
EMAIL_LOG_LEVEL=INFO

# reCAPTCHA Configuration (if using reCAPTCHA)
RECAPTCHA_SITE_KEY=your_recaptcha_site_key_here
RECAPTCHA_SECRET_KEY=your_recaptcha_secret_key_here

# Domain Configuration (for production)
DOMAIN_NAME=${WEBSITE_DOMAIN}

# Cloudflare Tunnel Configuration (for production)
# Set to true to skip tunnel setup (omit real CLOUDFLARE_* values below).
# SKIP_CLOUDFLARE_TUNNEL=false
CLOUDFLARE_TUNNEL_ID=your_tunnel_id_here
CLOUDFLARE_ACCOUNT_TAG=your_account_tag_here
CLOUDFLARE_TUNNEL_SECRET="your_tunnel_secret_here_in_quotes_because_of_equals_sign"

# Gunicorn Configuration
GUNICORN_WORKERS=1  # Number of worker processes (recommended: 2-4 for production, 1 for development)

# Application-specific configuration (customize as needed)
# Add any website-specific environment variables here
# Example:
# MAX_USERS=100
# FEATURE_FLAG_NEW_UI=true
# API_RATE_LIMIT=1000

# Stripe Configuration (optional, for paid subscriptions)
STRIPE_PUBLISHABLE_KEY=pk_test_your_stripe_publishable_key_here
STRIPE_SECRET_KEY=sk_test_your_stripe_secret_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here
STRIPE_PRICE_ID_MONTHLY=price_your_monthly_price_id_here
STRIPE_PRICE_ID_YEARLY=price_your_yearly_price_id_here
# Optional: lower monthly/yearly Stripe Price IDs until SUBSCRIPTION_PROMO_END_DATE (default first day of Sept 2026)
# STRIPE_PRICE_ID_MONTHLY_PROMO=price_...
# STRIPE_PRICE_ID_YEARLY_PROMO=price_...
# SUBSCRIPTION_PROMO_END_DATE=2026-09-01
# SUBSCRIPTION_PRO_PRICE_MONTHLY_PROMO=2.99
# SUBSCRIPTION_PRO_PRICE_YEARLY_PROMO=39.99

# Application URLs
APP_URL=http://localhost:${WEBSITE_PORT}
STRIPE_SUCCESS_URL=http://localhost:${WEBSITE_PORT}/subscription/success
STRIPE_CANCEL_URL=http://localhost:${WEBSITE_PORT}/subscription/cancel

# Testing Configuration (for development)
TEST_BASE_URL="http://localhost:${WEBSITE_PORT}"
EOF
    
    chown $SERVICE_USER:$SERVICE_USER "$WORKING_DIR/.env"
    chmod 600 "$WORKING_DIR/.env"

    print_status ".env template created at $WORKING_DIR/.env"
    print_warning "IMPORTANT: Update the following values in .env before running setup again:"
    print_warning "  - FLASK_SECRET_KEY (generate a secure random string)"
    print_warning "  - DB_PASSWORD (your database password)"
    print_warning "  - ADMIN_PASSWORD_IN_DB (if using admin features)"
    print_warning "  - MAIL_USERNAME and MAIL_PASSWORD (if using email features)"
    print_warning "  - RECAPTCHA_SITE_KEY and RECAPTCHA_SECRET_KEY (if using reCAPTCHA)"
    print_warning "  - CLOUDFLARE_TUNNEL_ID, CLOUDFLARE_ACCOUNT_TAG, CLOUDFLARE_TUNNEL_SECRET (for production), or SKIP_CLOUDFLARE_TUNNEL=true"
    print_warning "  - Uncomment either Development or Production configuration section"
    print_warning "  - Update website-specific variables at the top of this script"
    print_warning "  - Customize contact email addresses for your domain"
    print_warning ""
    print_warning "After updating .env, run: ./deployment_items/${WEBSITE_NAME}_setup.sh"
    exit 0
fi

# Determine if this is production or development
if [ "$FLASK_ENV" = "production" ]; then
    IS_PRODUCTION=true
    print_status "Running PRODUCTION setup..."
    
    # Check if we can use sudo for production
    check_sudo

    # Cloudflare tunnel: require real credentials, auto-create when cert.pem exists, or exit with how-to.
    if cloudflare_tunnel_skipped_via_env "$WORKING_DIR/.env"; then
        print_status "SKIP_CLOUDFLARE_TUNNEL is set — Cloudflare tunnel credentials are not required for this run."
    elif cloudflare_tunnel_env_is_configured "$WORKING_DIR/.env"; then
        print_status "Cloudflare tunnel credentials found in .env"
    else
        SERVICE_USER_HOME=$(getent passwd "$SERVICE_USER" | cut -d: -f6)
        CF_CERT="${SERVICE_USER_HOME}/.cloudflared/cert.pem"
        CLOUDFLARED_BIN="$(command -v cloudflared 2>/dev/null || true)"
        if [ -z "$CLOUDFLARED_BIN" ] && [ -x /usr/local/bin/cloudflared ]; then
            CLOUDFLARED_BIN="/usr/local/bin/cloudflared"
        fi
        PREFLIGHT_DOMAIN=$(grep '^DOMAIN_NAME=' "$WORKING_DIR/.env" 2>/dev/null | head -n1 | sed 's/^DOMAIN_NAME=//' | tr -d ' \t\r' || true)
        if [ -z "$PREFLIGHT_DOMAIN" ] || [ "$PREFLIGHT_DOMAIN" = "your_domain_here" ]; then
            PREFLIGHT_DOMAIN="$WEBSITE_DOMAIN"
        fi

        if [ -f "$CF_CERT" ] && [ -n "$CLOUDFLARED_BIN" ] && [ -x "$CLOUDFLARED_BIN" ] && command -v python3 >/dev/null 2>&1; then
            print_status "Cloudflare tunnel credentials missing; attempting cloudflared tunnel create as ${SERVICE_USER}..."
            mkdir -p "${SERVICE_USER_HOME}/.cloudflared"
            chown "$SERVICE_USER:$SERVICE_USER" "${SERVICE_USER_HOME}/.cloudflared"
            chmod 700 "${SERVICE_USER_HOME}/.cloudflared"
            CF_TUNNEL_NAME="${WEBSITE_NAME}-tunnel"
            CREATE_LOG=$(mktemp)
            set +e
            _q_home=$(printf '%q' "$SERVICE_USER_HOME")
            _q_cfbin=$(printf '%q' "$CLOUDFLARED_BIN")
            _q_tname=$(printf '%q' "$CF_TUNNEL_NAME")
            if [ "$(id -un)" = "$SERVICE_USER" ]; then
                HOME="$SERVICE_USER_HOME" "$CLOUDFLARED_BIN" tunnel create "$CF_TUNNEL_NAME" >"$CREATE_LOG" 2>&1
                CREATE_RC=$?
            else
                sudo -u "$SERVICE_USER" bash -lc "export HOME=${_q_home}; ${_q_cfbin} tunnel create ${_q_tname}" >"$CREATE_LOG" 2>&1
                CREATE_RC=$?
            fi
            set -e
            if [ "$CREATE_RC" != "0" ]; then
                print_error "cloudflared tunnel create failed (exit $CREATE_RC). Output:"
                cat "$CREATE_LOG" || true
                rm -f "$CREATE_LOG"
                cloudflare_tunnel_manual_setup_instructions "$PREFLIGHT_DOMAIN"
                exit 1
            fi
            CRED_PATH=$(grep -o 'Tunnel credentials written to [^[:space:]]*\.json' "$CREATE_LOG" 2>/dev/null | head -n1 | sed 's/Tunnel credentials written to //' | tr -d '\r')
            rm -f "$CREATE_LOG"
            if [ -z "$CRED_PATH" ] || [ ! -f "$CRED_PATH" ]; then
                CRED_PATH=$(find "${SERVICE_USER_HOME}/.cloudflared" -maxdepth 1 -name '*.json' -mmin -5 -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -n1 | cut -d' ' -f2-)
            fi
            if [ -z "$CRED_PATH" ] || [ ! -f "$CRED_PATH" ]; then
                print_error "Could not locate new tunnel credentials JSON under ${SERVICE_USER_HOME}/.cloudflared"
                cloudflare_tunnel_manual_setup_instructions "$PREFLIGHT_DOMAIN"
                exit 1
            fi
            NEW_TUNNEL_ID=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['TunnelID'])" "$CRED_PATH")
            NEW_ACCOUNT_TAG=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['AccountTag'])" "$CRED_PATH")
            NEW_TUNNEL_SECRET=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['TunnelSecret'])" "$CRED_PATH")
            cloudflare_update_env_tunnel_vars "$WORKING_DIR/.env" "$NEW_TUNNEL_ID" "$NEW_ACCOUNT_TAG" "$NEW_TUNNEL_SECRET"
            chown "$SERVICE_USER:$SERVICE_USER" "$CRED_PATH" 2>/dev/null || true
            chmod 600 "$CRED_PATH" 2>/dev/null || true
            print_status "Created Cloudflare tunnel ${CF_TUNNEL_NAME} and updated .env with credentials (${NEW_TUNNEL_ID})."
            if ! cloudflare_tunnel_env_is_configured "$WORKING_DIR/.env"; then
                print_error ".env was updated but Cloudflare tunnel values still look invalid — check $WORKING_DIR/.env"
                exit 1
            fi
        else
            if [ ! -f "$CF_CERT" ]; then
                print_warning "Missing Cloudflare origin cert: $CF_CERT (run: cloudflared tunnel login as ${SERVICE_USER})"
            fi
            if [ -z "$CLOUDFLARED_BIN" ] || [ ! -x "$CLOUDFLARED_BIN" ]; then
                print_warning "cloudflared binary not found in PATH or /usr/local/bin/cloudflared"
            fi
            if ! command -v python3 >/dev/null 2>&1; then
                print_warning "python3 not found (needed to parse tunnel credentials after auto-create)"
            fi
            cloudflare_tunnel_manual_setup_instructions "$PREFLIGHT_DOMAIN"
            exit 1
        fi
    fi
else
    IS_PRODUCTION=false
    print_status "Running DEVELOPMENT setup..."
fi

# Production: host must be prepared separately — webserver_setup/server_bootstrap.sh (not invoked from this script).
print_status "Installing system packages (if not already installed)..."
if [ "$IS_PRODUCTION" = true ]; then
    print_status "Verifying host bootstrap (shared Postgres/Redis, nginx include, secrets)..."
    if ! sudo podman container exists web-postgres 2>/dev/null; then
        print_error "Podman container 'web-postgres' not found."
        print_error "Run initial host setup first, e.g.: cd /path/to/webserver_setup && sudo ./server_bootstrap.sh"
        exit 1
    fi
    if ! sudo podman container exists web-redis 2>/dev/null; then
        print_error "Podman container 'web-redis' not found."
        print_error "Run initial host setup first, e.g.: cd /path/to/webserver_setup && sudo ./server_bootstrap.sh"
        exit 1
    fi
    if [ ! -f /etc/nginx/conf.d/00-sites-enabled.conf ]; then
        print_warning "Missing /etc/nginx/conf.d/00-sites-enabled.conf — nginx may not include /etc/nginx/sites-enabled/*.conf"
        print_warning "server_bootstrap.sh creates this file; add the include or re-run bootstrap."
    fi

    # Set up PostgreSQL database and user inside the shared Postgres container.
    # Your app’s host-based initialization/backup scripts keep using `psql/pg_dump -h localhost`,
    # because the Postgres container is published to 127.0.0.1:5432 by setup_containers_stack.sh.
    print_status "Setting up PostgreSQL database and user..."
    if [ -f "$WORKING_DIR/.env" ]; then
        DB_PASSWORD=$(grep "^DB_PASSWORD=" "$WORKING_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/^"//;s/"$//')
        print_status "Using password from .env file"
    else
        DB_PASSWORD="secure_password_2025"
        print_warning "No .env file found, using default password"
    fi
    
    # Escape single quotes for safe embedding in SQL string literals.
    DB_PASSWORD_ESCAPED="$(printf "%s" "$DB_PASSWORD" | sed "s/'/''/g")"
    POSTGRES_SUPERUSER_PASSWORD="$(sudo cat /etc/webserver/postgres_superuser_password 2>/dev/null || true)"
    if [ -z "$POSTGRES_SUPERUSER_PASSWORD" ]; then
        print_error "Missing Postgres superuser password file for the shared container."
        print_error "Expected: /etc/webserver/postgres_superuser_password"
        print_error "Run initial host setup first, e.g.: cd /path/to/webserver_setup && sudo ./server_bootstrap.sh"
        exit 1
    fi

    print_status "Waiting for shared Postgres to be ready..."
    PG_READY=0
    for _ in $(seq 1 30); do
        if sudo podman exec web-postgres pg_isready -U postgres -d postgres >/dev/null 2>&1; then
            PG_READY=1
            break
        fi
        sleep 1
    done
    if [ "$PG_READY" != "1" ]; then
        print_error "Postgres in container 'web-postgres' did not become ready in time."
        print_error "Check: sudo systemctl status web-postgres.service && sudo podman logs web-postgres"
        exit 1
    fi

    print_status "Creating Postgres user/db in container..."
    sudo podman exec -i web-postgres env PGPASSWORD="${POSTGRES_SUPERUSER_PASSWORD}" psql -U postgres -d postgres <<EOF
-- Create user if it doesn't exist (idempotent) and ensure password is correct.
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD_ESCAPED}';
        RAISE NOTICE 'Created user ${DB_USER}';
    ELSE
        RAISE NOTICE 'User ${DB_USER} already exists';
        ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD_ESCAPED}';
        RAISE NOTICE 'Updated password for ${DB_USER}';
    END IF;
END
\$\$;

-- Grant privileges
ALTER USER ${DB_USER} CREATEDB;
EOF

    DB_EXISTS="$(sudo podman exec -i web-postgres env PGPASSWORD="${POSTGRES_SUPERUSER_PASSWORD}" psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | tr -d '[:space:]')"
    if [ "$DB_EXISTS" != "1" ]; then
        print_status "Creating database ${DB_NAME}..."
        sudo podman exec -i web-postgres env PGPASSWORD="${POSTGRES_SUPERUSER_PASSWORD}" psql -U postgres -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
    else
        print_status "Database ${DB_NAME} already exists"
    fi

    # Ensure grants exist even if db was pre-existing.
    sudo podman exec -i web-postgres env PGPASSWORD="${POSTGRES_SUPERUSER_PASSWORD}" psql -U postgres -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"
    sudo podman exec -i web-postgres env PGPASSWORD="${POSTGRES_SUPERUSER_PASSWORD}" psql -U postgres -d "${DB_NAME}" -c "GRANT CREATE, USAGE ON SCHEMA public TO ${DB_USER};"

    print_status "Shared Postgres user/db ready"
else
    # Development: Check for required packages
    if ! command -v psql &> /dev/null; then
        print_error "PostgreSQL not found. Please install it first:"
        echo "  Fedora: sudo dnf install postgresql16 postgresql16-server postgresql16-contrib"
        echo "  Then initialize and start: sudo postgresql-setup --initdb && sudo systemctl start postgresql"
        exit 1
    fi
    
    # Check if PostgreSQL is running
    if ! systemctl is-active --quiet postgresql; then
        print_warning "PostgreSQL is not running. Starting it..."
        check_sudo
        sudo systemctl start postgresql
    fi
    
    resolve_dev_python
    
    print_status "Required packages found"
    
    # Create database and user for development
    print_status "Setting up PostgreSQL database and user for development..."
    if [ -f "$WORKING_DIR/.env" ]; then
        DB_PASSWORD=$(grep "^DB_PASSWORD=" "$WORKING_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/^"//;s/"$//')
        print_status "Using password from .env file"
    else
        DB_PASSWORD="secure_password_2025"
        print_warning "No .env file found, using default password"
    fi

    # Create database and user
    sudo -u postgres psql << EOF
-- Create user if it doesn't exist
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        RAISE NOTICE 'Created user $DB_USER';
    ELSE
        RAISE NOTICE 'User $DB_USER already exists';
        -- Update password to ensure it's correct
        ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        RAISE NOTICE 'Updated password for $DB_USER';
    END IF;
END
\$\$;

-- Grant privileges
ALTER USER $DB_USER CREATEDB;
EOF

    DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | tr -d '[:space:]')
    if [ "$DB_EXISTS" != "1" ]; then
        print_status "Creating database $DB_NAME..."
        sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
    else
        print_status "Database $DB_NAME already exists"
    fi

    # Ensure grants exist even if db was pre-existing.
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
    sudo -u postgres psql -d "$DB_NAME" -c "GRANT CREATE, USAGE ON SCHEMA public TO $DB_USER;"

    print_status "Database and user created successfully"
fi

# Set up Python virtual environment and dependencies (development only).
# In production, the app runs in a container image and dependencies are installed during image build.
if [ "$IS_PRODUCTION" = false ]; then
    print_status "Setting up Python virtual environment and dependencies..."
    cd "$WORKING_DIR"
    if [ ! -d "venv" ]; then
        "${DEV_PYTHON_RESOLVED}" -m venv venv
    else
        if [ -x "venv/bin/python" ]; then
            venv_py_ver="$(venv/bin/python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
            if [ -n "${DEV_PYTHON_VERSION_EXPECTED:-}" ] && [ "$venv_py_ver" != "$DEV_PYTHON_VERSION_EXPECTED" ]; then
                print_warning "Existing venv uses Python ${venv_py_ver}; expected ${DEV_PYTHON_VERSION_EXPECTED}."
                print_warning "Fix: rm -rf venv && re-run this script (development), or: ${DEV_PYTHON_RESOLVED} -m venv venv --clear"
            fi
        fi
    fi
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    print_status "Skipping host venv/dependency install in production (containerized runtime)"
fi

# .env file already exists and was validated at the start
print_status "Using existing .env file configuration"
chown $SERVICE_USER:$SERVICE_USER "$WORKING_DIR/.env"
chmod 600 "$WORKING_DIR/.env"

# Initialize database (development only). In production, app startup handles schema/init in container.
if [ "$IS_PRODUCTION" = false ]; then
    print_status "Initializing database..."
    cd "$WORKING_DIR"
    source venv/bin/activate

    # Set PGPASSWORD environment variable for password authentication
    export PGPASSWORD="$DB_PASSWORD"

    # Test database connection first
    print_status "Testing database connection..."
    if ! psql -h localhost -U $DB_USER -d $DB_NAME -c "SELECT 1;" >/dev/null 2>&1; then
        print_error "Cannot connect to database. Please check:"
        print_error "1. PostgreSQL is running: sudo systemctl status postgresql"
        print_error "2. Database exists: psql -h localhost -U $DB_USER -d $DB_NAME -c '\\l'"
        print_error "3. User has correct password: check .env file DB_PASSWORD"
        exit 1
    fi
    print_status "Database connection successful"

    # Check if database tables already exist
    print_status "Checking if database tables exist..."
    TABLE_CHECK=$(psql -h localhost -U $DB_USER -d $DB_NAME -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null || echo "0")

    if [ "$TABLE_CHECK" -gt 0 ]; then
        print_status "Database tables already exist - skipping initialization"
        print_warning "If you need to reset the database, run: python setup_database.py --reset"
    else
        print_status "Database tables not found - initializing..."
        if [ -f "setup_database.py" ]; then
            python setup_database.py
            print_status "Database initialized successfully"
        else
            print_warning "setup_database.py not found - you may need to run database setup manually"
        fi
    fi
else
    print_status "Skipping host DB init in production (containerized app initializes DB on startup)"
fi

# Ensure backup script exists (runs in both dev and prod)
if [ ! -f "$SCRIPT_DIR/${BACKUP_SCRIPT}" ]; then
    print_status "Creating ${BACKUP_SCRIPT} (DB-only)..."
    cat > "$SCRIPT_DIR/${BACKUP_SCRIPT}" << EOF
#!/bin/bash

# ${WEBSITE_NAME^} Database Backup Script (DB-only)

set -e

# Configuration
APP_NAME="${WEBSITE_NAME}"
APP_DIR="$WORKING_DIR"
BACKUP_DIR="/home/${SERVICE_USER}/backups/${WEBSITE_NAME}"
DB_NAME="${DB_NAME}"
DB_USER="${DB_USER}"
GDRIVE_REMOTE="\${GDRIVE_REMOTE:-gdrive}"
RCLONE_CONFIG="\${RCLONE_CONFIG:-/root/.config/rclone/rclone.conf}"
GDRIVE_PATH="${WEBSITE_NAME}"
TIMESTAMP=\$(date +"%Y%m%d_%H%M%S")
LOG_FILE="\${BACKUP_DIR}/backup.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() { echo -e "\${GREEN}[+]\${NC} \$1"; }
print_warning() { echo -e "\${YELLOW}[!]\${NC} \$1"; }
print_error() { echo -e "\${RED}[-]\${NC} \$1"; }

# Create backup directory if it doesn't exist
mkdir -p "\$BACKUP_DIR"

# Function to log messages
log_message() {
    echo "[\$(date '+%Y-%m-%d %H:%M:%S')] \$1" | tee -a "\$LOG_FILE"
}

log_message "=== Starting DB backup for ${WEBSITE_NAME} ==="

DB_PASSWORD=\$(grep "^DB_PASSWORD=" "\$APP_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/^"//;s/"$//')
if [ -z "\$DB_PASSWORD" ]; then log_message "ERROR: DB_PASSWORD not found in .env"; exit 1; fi

if PGPASSWORD="\$DB_PASSWORD" pg_dump -h localhost -U \$DB_USER -d \$DB_NAME > "\${BACKUP_DIR}/database_backup_\$TIMESTAMP.sql"; then
    log_message "Database backup created successfully"
else
    log_message "ERROR: Database backup failed"; exit 1
fi

# Keep only the last 7 SQL backups
cd "\$BACKUP_DIR"
ls -t database_backup_*.sql | tail -n +8 | xargs -r rm -f

log_message "Syncing backups to Google Drive (if configured)..."
if command -v rclone >/dev/null 2>&1; then
    # If requested remote isn't present, fall back to first configured remote.
    if ! rclone --config "\$RCLONE_CONFIG" listremotes 2>/dev/null | grep -Fxq "\${GDRIVE_REMOTE}:"; then
        DETECTED_REMOTE="\$(rclone --config "\$RCLONE_CONFIG" listremotes 2>/dev/null | sed -n '1s/:$//p')"
        if [ -n "\$DETECTED_REMOTE" ]; then
            log_message "INFO: Remote '\$GDRIVE_REMOTE' not found; using '\$DETECTED_REMOTE' from \$RCLONE_CONFIG"
            GDRIVE_REMOTE="\$DETECTED_REMOTE"
        fi
    fi
    if [ -n "\$GDRIVE_REMOTE" ] && rclone --config "\$RCLONE_CONFIG" copy "\$BACKUP_DIR" "\$GDRIVE_REMOTE:/\$GDRIVE_PATH" --log-level=ERROR >> "\$BACKUP_DIR/gdrive-sync.log" 2>&1; then
        log_message "Google Drive sync completed"
    else
        log_message "WARNING: Google Drive sync failed"
    fi
else
    log_message "Google Drive sync not configured (rclone not found)"
fi

log_message "=== DB backup completed ==="
EOF
    chmod +x "$SCRIPT_DIR/${BACKUP_SCRIPT}"
    chown $SERVICE_USER:$SERVICE_USER "$SCRIPT_DIR/${BACKUP_SCRIPT}"
    print_status "Backup script created: $SCRIPT_DIR/${BACKUP_SCRIPT}"
else
    print_status "Backup script already exists: $SCRIPT_DIR/${BACKUP_SCRIPT}"
fi

# Ensure restore script exists and is up-to-date (runs in both dev and prod)
print_status "Creating/updating restore_${WEBSITE_NAME} (DB-only)..."
cat > "$SCRIPT_DIR/restore_${WEBSITE_NAME}" << 'TEMPLATE_EOF'
#!/bin/bash

# WEBSITE_NAME_PLACEHOLDER Database Restore Script (DB-only)
#
# Usage:
#   ./restore_WEBSITE_NAME_PLACEHOLDER
#       With no args: uses .sql file(s) in deployment_items/backup_to_restore/
#   ./restore_WEBSITE_NAME_PLACEHOLDER <timestamp|filename|path>
#       See usage output for resolution order.

set -e

APP_NAME="WEBSITE_NAME_PLACEHOLDER"
APP_DIR="WORKING_DIR_PLACEHOLDER"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_RESTORE_DIR="$SCRIPT_DIR/backup_to_restore"
BACKUP_DIR="/home/${SERVICE_USER}/backups/WEBSITE_NAME_PLACEHOLDER"
DB_NAME="DB_NAME_PLACEHOLDER"
DB_USER="DB_USER_PLACEHOLDER"
SERVICE_NAME="WEBSITE_NAME_PLACEHOLDER"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >&2; }

usage() {
  echo "Usage: $0 [timestamp|sql_file|path]"
  echo ""
  echo "With no arguments: use a .sql file in:"
  echo "  $LOCAL_RESTORE_DIR"
  echo ""
  echo "With an argument, resolution order:"
  echo "  1) Path if that file already exists"
  echo "  2) $LOCAL_RESTORE_DIR/<argument>"
  echo "  3) $BACKUP_DIR/database_backup_<argument>.sql"
  echo "  4) $BACKUP_DIR/<argument> if it matches database_backup_*.sql"
  echo ""
  echo "Server backup directory (from backup cron):"
  ls -1 "$BACKUP_DIR"/database_backup_*.sql 2>/dev/null | sed "s|$BACKUP_DIR/||" || echo "  (none found)"
}

pick_local_backup() {
  mkdir -p "$LOCAL_RESTORE_DIR"
  local -a candidates=()
  shopt -s nullglob
  candidates=("$LOCAL_RESTORE_DIR"/*.sql)
  shopt -u nullglob

  local n=${#candidates[@]}
  if [ "$n" -eq 0 ]; then
    return 1
  fi

  if [ "$n" -eq 1 ]; then
    log "Found SQL dump in backup_to_restore/: $(basename "${candidates[0]}")"
    read -r -p "Use this file for restore? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
      log "Restoration cancelled"
      exit 0
    fi
    printf '%s\n' "${candidates[0]}"
    return 0
  fi

  log "Multiple .sql files in backup_to_restore/:"
  local i=1
  for f in "${candidates[@]}"; do
    echo "  $i) $(basename "$f")" >&2
    i=$((i + 1))
  done
  read -r -p "Enter number (1-$n) or c to cancel: " pick
  if [ "$pick" = "c" ] || [ "$pick" = "C" ]; then
    log "Restoration cancelled"
    exit 0
  fi
  if ! [[ "$pick" =~ ^[0-9]+$ ]] || [ "$pick" -lt 1 ] || [ "$pick" -gt "$n" ]; then
    log "ERROR: Invalid selection"
    exit 1
  fi
  printf '%s\n' "${candidates[$((pick - 1))]}"
  return 0
}

resolve_backup_path() {
  local input="$1"
  if [ -f "$input" ]; then
    printf '%s\n' "$(cd "$(dirname "$input")" && pwd)/$(basename "$input")"
    return 0
  fi
  if [ -f "$LOCAL_RESTORE_DIR/$input" ]; then
    printf '%s\n' "$LOCAL_RESTORE_DIR/$input"
    return 0
  fi
  if [[ "$input" == database_backup_*.sql ]] && [ -f "$BACKUP_DIR/$input" ]; then
    printf '%s\n' "$BACKUP_DIR/$input"
    return 0
  fi
  local server_path="$BACKUP_DIR/database_backup_${input}.sql"
  if [ -f "$server_path" ]; then
    printf '%s\n' "$server_path"
    return 0
  fi
  return 1
}

if [ $# -eq 0 ]; then
  if ! DB_SQL="$(pick_local_backup)"; then
    log "ERROR: No .sql files in $LOCAL_RESTORE_DIR"
    echo "Copy a PostgreSQL dump (.sql) into that directory, or pass a timestamp/filename." >&2
    usage
    exit 1
  fi
else
  if ! DB_SQL="$(resolve_backup_path "$1")"; then
    log "ERROR: Database SQL not found for: $1"
    usage
    exit 1
  fi
fi

[ -f "$DB_SQL" ] || { log "ERROR: Database SQL not found: $DB_SQL"; exit 1; }

log "Selected dump: $DB_SQL"

echo "" >&2
echo "WARNING: This will OVERWRITE the current database only." >&2
read -r -p "Are you sure you want to continue? (yes/no): " confirm
[ "$confirm" = "yes" ] || { log "Restoration cancelled"; exit 0; }

log "Stopping $SERVICE_NAME (Quadlet may use .service, -container, or container- prefix)..."
sudo systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
sudo systemctl stop "${SERVICE_NAME}-container.service" 2>/dev/null || true
sudo systemctl stop "container-${SERVICE_NAME}.service" 2>/dev/null || true

DB_PASSWORD=$(grep "^DB_PASSWORD=" "$APP_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/^"//;s/"$//')
PGPASSWORD="$DB_PASSWORD" psql -h localhost -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
PGPASSWORD="$DB_PASSWORD" psql -h localhost -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
PGPASSWORD="$DB_PASSWORD" psql -h localhost -U "$DB_USER" -d "$DB_NAME" < "$DB_SQL"

log "Starting $SERVICE_NAME container unit..."
sudo systemctl start "${SERVICE_NAME}.service" 2>/dev/null || true
sudo systemctl start "${SERVICE_NAME}-container.service" 2>/dev/null || true
sudo systemctl start "container-${SERVICE_NAME}.service" 2>/dev/null || true

log "DB Restore complete"
TEMPLATE_EOF
# Substitute setup-time variables (only these should be replaced)
sed -i "s|WEBSITE_NAME_PLACEHOLDER|${WEBSITE_NAME}|g" "$SCRIPT_DIR/restore_${WEBSITE_NAME}"
sed -i "s|WORKING_DIR_PLACEHOLDER|${WORKING_DIR}|g" "$SCRIPT_DIR/restore_${WEBSITE_NAME}"
sed -i "s|DB_NAME_PLACEHOLDER|${DB_NAME}|g" "$SCRIPT_DIR/restore_${WEBSITE_NAME}"
sed -i "s|DB_USER_PLACEHOLDER|${DB_USER}|g" "$SCRIPT_DIR/restore_${WEBSITE_NAME}"
chmod +x "$SCRIPT_DIR/restore_${WEBSITE_NAME}"
chown $SERVICE_USER:$SERVICE_USER "$SCRIPT_DIR/restore_${WEBSITE_NAME}" 2>/dev/null || true
print_status "Restore script created/updated: $SCRIPT_DIR/restore_${WEBSITE_NAME}"

# Maintenance mode functionality removed

# Production-only setup
if [ "$IS_PRODUCTION" = true ]; then
    print_status "Setting up production infrastructure..."
    # Server-wide packages, cloudflared binary, firewall, fail2ban, etc.: already applied by server_bootstrap.sh (run separately before this script).

    # Nightly DB backup — root crontab (matches legacy server behavior and avoids backup dir permission issues).
    # Override schedule with: BACKUP_CRON_SCHEDULE="m h dom mon dow"
    mkdir -p "$WORKING_DIR/logs"
    BACKUP_CRON_SCHEDULE="${BACKUP_CRON_SCHEDULE:-0 2 * * *}"
    ROOT_CRONTAB="$(sudo crontab -l 2>/dev/null || true)"
    if ! printf "%s\n" "$ROOT_CRONTAB" | grep -Fq "$SCRIPT_DIR/${BACKUP_SCRIPT}"; then
        (printf "%s\n" "$ROOT_CRONTAB"; echo "${BACKUP_CRON_SCHEDULE} $SCRIPT_DIR/${BACKUP_SCRIPT}") | sudo crontab -
        print_status "Added root crontab: DB backup at '${BACKUP_CRON_SCHEDULE}' (script logs to backups dir via backup.log)"
    else
        print_status "DB backup cron already present in root crontab — skipping"
    fi

    # Setup Cloudflare Tunnel (dedicated per-site tunnel)
    print_status "Setting up Cloudflare Tunnel..."
    # Prefer WEBSITE_DOMAIN, but allow DOMAIN_NAME in .env for backwards compatibility
    DOMAIN_NAME="${WEBSITE_DOMAIN}"
    ENV_DOMAIN_NAME=$(grep "^DOMAIN_NAME=" "$WORKING_DIR/.env" | cut -d'=' -f2 | tr -d ' ' || true)
    if [ -n "$ENV_DOMAIN_NAME" ] && [ "$ENV_DOMAIN_NAME" != "your_domain_here" ]; then
        DOMAIN_NAME="$ENV_DOMAIN_NAME"
    fi
    TUNNEL_ID=$(grep "^CLOUDFLARE_TUNNEL_ID=" "$WORKING_DIR/.env" | cut -d'=' -f2 | tr -d ' ')
    ACCOUNT_TAG=$(grep "^CLOUDFLARE_ACCOUNT_TAG=" "$WORKING_DIR/.env" | cut -d'=' -f2 | tr -d ' ')
    TUNNEL_SECRET=$(grep "^CLOUDFLARE_TUNNEL_SECRET=" "$WORKING_DIR/.env" | sed 's/^CLOUDFLARE_TUNNEL_SECRET=//' | tr -d '"')
    
    if [ -n "$TUNNEL_ID" ] && [ "$TUNNEL_ID" != "your_tunnel_id_here" ]; then
        print_status "Configuring Cloudflare Tunnel with ID: $TUNNEL_ID"
        
        # Create cloudflared directory and set permissions (don't overwrite existing)
        mkdir -p /home/$SERVICE_USER/.cloudflared
        chown -R $SERVICE_USER:$SERVICE_USER /home/$SERVICE_USER/.cloudflared
        chmod 700 /home/$SERVICE_USER/.cloudflared
        
        # Create credentials file (only if it doesn't exist for this tunnel)
        if [ ! -f /home/$SERVICE_USER/.cloudflared/${TUNNEL_ID}.json ]; then
            print_status "Creating credentials file for tunnel ${TUNNEL_ID}..."
            cat > /home/$SERVICE_USER/.cloudflared/${TUNNEL_ID}.json << EOF
{
    "AccountTag": "${ACCOUNT_TAG}",
    "TunnelSecret": "${TUNNEL_SECRET}",
    "TunnelID": "${TUNNEL_ID}",
    "Endpoint": ""
}
EOF
            chmod 600 /home/$SERVICE_USER/.cloudflared/${TUNNEL_ID}.json
            print_status "Credentials file created"
        else
            print_status "Credentials file for tunnel ${TUNNEL_ID} already exists"
        fi
        
        # Generate origin certificate if it doesn't exist
        if [ ! -f /home/$SERVICE_USER/.cloudflared/cert.pem ]; then
            print_status "Generating Cloudflare origin certificate..."
            cloudflared tunnel login
            print_status "Origin certificate generated"
        else
            print_status "Origin certificate already exists"
        fi
        
        # Create per-site cloudflared config (dedicated tunnel)
        CF_CONFIG_PATH="/home/$SERVICE_USER/.cloudflared/${WEBSITE_NAME}-config.yml"
        print_status "Creating/updating ${WEBSITE_NAME}-config.yml..."
        cat > "${CF_CONFIG_PATH}" << EOF
tunnel: ${TUNNEL_ID}
credentials-file: /home/$SERVICE_USER/.cloudflared/${TUNNEL_ID}.json
originRequest:
  noTLSVerify: true
  disableChunkedEncoding: true
ingress:
  - hostname: ${DOMAIN_NAME}
    service: http://127.0.0.1:${WEBSITE_PORT}
  - service: http_status:404
EOF
        chmod 600 "${CF_CONFIG_PATH}"
        
        # Set proper ownership for directory contents
        chown -R $SERVICE_USER:$SERVICE_USER /home/$SERVICE_USER/.cloudflared
        if [ -f /home/$SERVICE_USER/.cloudflared/cert.pem ]; then
            chmod 600 /home/$SERVICE_USER/.cloudflared/cert.pem
        fi
        
        print_status "Cloudflare Tunnel configured for ${DOMAIN_NAME} (config: ${CF_CONFIG_PATH})"
        HAS_CLOUDFLARE_TUNNEL=1
    else
        print_warning "Cloudflare Tunnel configuration not found in .env - skipping tunnel setup"
        print_warning "Add CLOUDFLARE_TUNNEL_ID, CLOUDFLARE_ACCOUNT_TAG, and CLOUDFLARE_TUNNEL_SECRET to .env"
        HAS_CLOUDFLARE_TUNNEL=0
    fi

    if [ "${HAS_CLOUDFLARE_TUNNEL:-0}" != "1" ]; then
        sudo systemctl disable --now "cloudflared-${WEBSITE_NAME}" 2>/dev/null || true
        sudo rm -f "/etc/systemd/system/cloudflared-${WEBSITE_NAME}.service"
    fi
    
    # Get Gunicorn workers from .env or use default
    ENV_GUNICORN_WORKERS=""
    if [ -f "$WORKING_DIR/.env" ]; then
        # Strip inline # comments and whitespace (otherwise "1  # comment" becomes "1#comment" after tr -d ' ').
        ENV_GUNICORN_WORKERS=$(grep "^GUNICORN_WORKERS=" "$WORKING_DIR/.env" | head -n1 | sed 's/^[^=]*=//' | sed 's/[[:space:]]*#.*//' | tr -d ' \t"')
        if [ -n "$ENV_GUNICORN_WORKERS" ]; then
            GUNICORN_WORKERS="$ENV_GUNICORN_WORKERS"
        fi
    fi
    # Validate workers count (must be positive integer)
    if ! [[ "$GUNICORN_WORKERS" =~ ^[1-9][0-9]*$ ]]; then
        if [ -n "$ENV_GUNICORN_WORKERS" ]; then
            print_warning "Invalid GUNICORN_WORKERS value ($ENV_GUNICORN_WORKERS), using default: 1"
        fi
        GUNICORN_WORKERS="1"
    fi
    print_status "Using Gunicorn workers: $GUNICORN_WORKERS"
    
    # Build and run the Flask app as a Quadlet-managed container.
    # This replaces the host-managed Gunicorn systemd service.
    LOCAL_IMAGE_NAME="localhost/${WEBSITE_NAME}:latest"
    LEGACY_IMAGE_NAME="${WEBSITE_NAME}:latest"
    print_status "Building container image for ${WEBSITE_NAME}..."
    if ! sudo podman image exists "${LOCAL_IMAGE_NAME}" >/dev/null 2>&1; then
        if sudo podman image exists "${LEGACY_IMAGE_NAME}" >/dev/null 2>&1; then
            print_status "Tagging existing image ${LEGACY_IMAGE_NAME} as ${LOCAL_IMAGE_NAME}..."
            sudo podman tag "${LEGACY_IMAGE_NAME}" "${LOCAL_IMAGE_NAME}"
        else
            sudo podman build -t "${LOCAL_IMAGE_NAME}" -f "$WORKING_DIR/Containerfile" "$WORKING_DIR"
        fi
    else
        print_status "Container image already exists: ${LOCAL_IMAGE_NAME}"
    fi

    print_status "Setting up containerized systemd (Quadlet) unit..."
    sudo rm -f "/etc/systemd/system/${WEBSITE_NAME}.service" 2>/dev/null || true

    # Run the app as the deploy user so bind-mounted logs and __pycache__ are not root-owned on the host.
    DEPLOY_UID=$(id -u "$SERVICE_USER")
    DEPLOY_GID=$(id -g "$SERVICE_USER")

    sudo tee /etc/containers/systemd/${WEBSITE_NAME}.container > /dev/null << EOF
[Unit]
Description=Containerized Gunicorn instance for ${WEBSITE_NAME}
After=web-postgres.service web-redis.service network-online.target

[Container]
ContainerName=${WEBSITE_NAME}
Image=${LOCAL_IMAGE_NAME}
Pull=never
Network=webserver-net
User=${DEPLOY_UID}
Group=${DEPLOY_GID}
# Ensure external SMTP hostnames resolve from inside the container.
DNS=1.1.1.1
DNS=8.8.8.8
Volume=$WORKING_DIR:/opt/${WEBSITE_NAME}:Z
PublishPort=127.0.0.1:${WEBSITE_PORT}:${WEBSITE_PORT}
Environment=DB_HOST=web-postgres
Environment=REDIS_HOST=web-redis
Exec=/bin/sh -c "cd /opt/${WEBSITE_NAME} && exec gunicorn --workers ${GUNICORN_WORKERS} --bind 0.0.0.0:${WEBSITE_PORT} app.app:app"

[Service]
# Keep this as a system/root-managed container unit so image storage/context
# matches the sudo podman build/tag operations in this setup script.
Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    # Cloudflared systemd unit only when .env has a real tunnel (avoids failed units on hosts without Cloudflare)
    if [ "${HAS_CLOUDFLARE_TUNNEL:-0}" = "1" ]; then
        CLOUDFLARED_BIN="$(command -v cloudflared 2>/dev/null || true)"
        if [ -z "$CLOUDFLARED_BIN" ] && [ -x /usr/local/bin/cloudflared ]; then
            CLOUDFLARED_BIN="/usr/local/bin/cloudflared"
        fi
        if [ -z "$CLOUDFLARED_BIN" ]; then
            print_error "cloudflared not found in PATH (install via server_bootstrap.sh or dnf)."
            exit 1
        fi
        print_status "Creating cloudflared-${WEBSITE_NAME}.service (using ${CLOUDFLARED_BIN})..."
        sudo tee /etc/systemd/system/cloudflared-${WEBSITE_NAME}.service > /dev/null << EOF
[Unit]
Description=Cloudflare Tunnel (${WEBSITE_NAME})
After=network-online.target systemd-resolved.service
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$WORKING_DIR
ExecStart=${CLOUDFLARED_BIN} tunnel --config /home/$SERVICE_USER/.cloudflared/${WEBSITE_NAME}-config.yml run
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5

[Install]
WantedBy=multi-user.target
EOF
    fi
    
    # Set up rclone (Google Drive) configuration for user if missing
    print_status "Checking rclone configuration..."
    USER_RCLONE_DIR="/home/$SERVICE_USER/.config/rclone"
    USER_RCLONE_CONF="$USER_RCLONE_DIR/rclone.conf"
    sudo -u "$SERVICE_USER" mkdir -p "$USER_RCLONE_DIR"

    # If missing, warn with instructions (server_bootstrap.sh should seed this once per host)
    if [ ! -f "$USER_RCLONE_CONF" ]; then
        print_warning "rclone.conf not found for user. Seed it via webserver_setup/server_bootstrap.sh"
        print_warning "Or configure it interactively as $SERVICE_USER:"
        print_warning "  sudo -u $SERVICE_USER rclone config"
        print_warning "  (Create remote named 'gdrive', type 'drive')"
        print_warning "Then verify with: sudo -u $SERVICE_USER rclone lsd gdrive:"
    else
        print_status "rclone user configuration is present"
    fi

    # Setup rclone config for root (needed for Google Drive sync)
    print_status "Setting up rclone configuration for root..."
    if [ -f "/home/$SERVICE_USER/.config/rclone/rclone.conf" ]; then
        sudo mkdir -p /root/.config/rclone
        sudo cp "/home/$SERVICE_USER/.config/rclone/rclone.conf" /root/.config/rclone/rclone.conf
        sudo chown root:root /root/.config/rclone/rclone.conf
        sudo chmod 600 /root/.config/rclone/rclone.conf
        print_status "rclone config copied to root directory"
    else
        print_warning "rclone config not found at /home/$SERVICE_USER/.config/rclone/rclone.conf"
        print_warning "Google Drive sync will not work until rclone is configured"
    fi

    # Create restore script if it doesn't exist
    print_status "Creating restore script..."
    if [ ! -f "$SCRIPT_DIR/restore_${WEBSITE_NAME}" ]; then
        cat > "$SCRIPT_DIR/restore_${WEBSITE_NAME}" << 'EOF'
#!/bin/bash

# Restore Script for ${WEBSITE_NAME}
# Usage: restore_${WEBSITE_NAME} <timestamp|backup_tar>

set -e

APP_NAME="${WEBSITE_NAME}"
APP_DIR="$WORKING_DIR"
#APP_DIR="/home/${SERVICE_USER}/${WEBSITE_NAME}"  # Production
BACKUP_DIR="/home/${SERVICE_USER}/backups/${WEBSITE_NAME}"
DB_NAME="${DB_NAME}"
DB_USER="${DB_USER}"
SERVICE_NAME="${WEBSITE_NAME}"

log() { echo "[\$(date '+%Y-%m-%d %H:%M:%S')] \$1"; }
usage() {
  echo "Usage: \$0 <timestamp|backup_tar>"
  echo "Available backups:"; ls -1 "$BACKUP_DIR"/${APP_NAME}_backup_*.tar.gz 2>/dev/null | sed "s|$BACKUP_DIR/||" || true
}

[ \$# -gt 0 ] || { log "ERROR: No parameter provided"; usage; exit 1; }

INPUT="\$1"
TIMESTAMP=""
BACKUP_TAR=""
DB_SQL=""

if [[ "\$INPUT" == *.tar.gz ]]; then
  BACKUP_TAR="$BACKUP_DIR/\$INPUT"
  TIMESTAMP=$(echo "$INPUT" | sed -n "s/^${APP_NAME}_backup_\(.*\)\.tar\.gz$/\1/p")
else
  TIMESTAMP="\$INPUT"
  BACKUP_TAR="$BACKUP_DIR/${APP_NAME}_backup_\$TIMESTAMP.tar.gz"
fi

DB_SQL="$BACKUP_DIR/database_backup_\$TIMESTAMP.sql"

[ -f "$BACKUP_TAR" ] || { log "ERROR: Backup tar not found: $BACKUP_TAR"; exit 1; }
[ -f "$DB_SQL" ] || { log "ERROR: Database SQL not found: $DB_SQL"; exit 1; }

echo "\nWARNING: This will OVERWRITE the current database and restore app files."
read -p "Are you sure you want to continue? (yes/no): " confirm
[ "\$confirm" = "yes" ] || { log "Restoration cancelled"; exit 0; }

log "Stopping \$SERVICE_NAME service..."
sudo systemctl stop "\$SERVICE_NAME" || true

TEMP_DIR="/tmp/restore_\${APP_NAME}_\$(date +%s)"
mkdir -p "\$TEMP_DIR"

try_tar() { tar -xzf "\$1" -C "\$2" 2>/dev/null || tar -xzf "\$1" -C "\$2" --warning=no-unknown-keyword; }
try_tar "\$BACKUP_TAR" "\$TEMP_DIR"
rsync -a --delete --exclude 'venv' --exclude 'logs' "\$TEMP_DIR/" "\$APP_DIR/"

DB_PASSWORD=$(grep "^DB_PASSWORD=" "$APP_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/^"//;s/"$//')
PGPASSWORD="\$DB_PASSWORD" psql -h localhost -U "\$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS \$DB_NAME;"
PGPASSWORD="\$DB_PASSWORD" psql -h localhost -U "\$DB_USER" -d postgres -c "CREATE DATABASE \$DB_NAME OWNER \$DB_USER;"
PGPASSWORD="\$DB_PASSWORD" psql -h localhost -U "\$DB_USER" -d "\$DB_NAME" < "\$DB_SQL"

rm -rf "\$TEMP_DIR"

log "Starting \$SERVICE_NAME service..."
sudo systemctl start "\$SERVICE_NAME" || true

log "Restore complete"
EOF
        chmod +x "$SCRIPT_DIR/restore_${WEBSITE_NAME}"
        chown $SERVICE_USER:$SERVICE_USER "$SCRIPT_DIR/restore_${WEBSITE_NAME}"
        print_status "Restore script created: $SCRIPT_DIR/restore_${WEBSITE_NAME}"
    else
        print_status "Restore script already exists: $SCRIPT_DIR/restore_${WEBSITE_NAME}"
    fi

    if [ "${HAS_CLOUDFLARE_TUNNEL:-0}" = "1" ]; then
    # Host-wide cloudflared updater (not tied to a project directory)
    WEBSERVER_ETC="${WEBSERVER_ETC:-/etc/webserver}"
    CF_UPDATE_SCRIPT="${WEBSERVER_ETC}/update_cloudflared.sh"
    WS_REPO="/home/$SERVICE_USER/webserver_setup"
    CF_SRC="${WS_REPO}/deployment_items/update_cloudflared.sh"
    print_status "Installing host-wide cloudflared update script: ${CF_UPDATE_SCRIPT}"
    sudo mkdir -p "${WEBSERVER_ETC}"
    if [ ! -f "$CF_SRC" ]; then
        print_error "Missing $CF_SRC — clone webserver_setup beside app repos"
        exit 1
    fi
    sudo install -m 0755 "$CF_SRC" "${CF_UPDATE_SCRIPT}"

    print_status "Setting up cron job for daily cloudflared update (root crontab)..."
    if ! sudo crontab -l 2>/dev/null | grep -Fq "${CF_UPDATE_SCRIPT}"; then
        (sudo crontab -l 2>/dev/null; echo "45 1 * * * ${CF_UPDATE_SCRIPT}") | sudo crontab -
        print_status "Cloudflared update cron added: 45 1 * * * ${CF_UPDATE_SCRIPT}"
    else
        print_status "Cloudflared update cron already references ${CF_UPDATE_SCRIPT} — skipping"
    fi
    UC_CRON_LINES=$(sudo crontab -l 2>/dev/null | grep -c 'update_cloudflared\.sh' || true)
    if [ "${UC_CRON_LINES:-0}" -gt 1 ]; then
        print_warning "Root crontab has multiple update_cloudflared lines ($UC_CRON_LINES). Run: sudo crontab -l"
        print_warning "Keep a single job: ${CF_UPDATE_SCRIPT}"
    elif [ "${UC_CRON_LINES:-0}" -eq 1 ] && ! sudo crontab -l 2>/dev/null | grep -Fq "${CF_UPDATE_SCRIPT}"; then
        print_warning "Cron still points at an old path; switch to: ${CF_UPDATE_SCRIPT} (sudo crontab -e)"
    fi
    fi

    # DDNS + daily reboot crons live in webserver_setup/server_bootstrap.sh (/etc/webserver/cloudflare_ddns.conf)

    # Configure Nginx with dynamic domain support
    print_status "Configuring Nginx..."
    
    # Create sites-available directory if it doesn't exist (Fedora compatibility)
    sudo mkdir -p /etc/nginx/sites-available
    sudo mkdir -p /etc/nginx/sites-enabled
    if [ -n "$DOMAIN_NAME" ] && [ "$DOMAIN_NAME" != "your_domain_here" ]; then
        print_status "Configuring Nginx for domain: $DOMAIN_NAME"
        
        # Create Nginx configuration with SSL redirect
        sudo tee /etc/nginx/sites-available/${WEBSITE_NAME} > /dev/null << EOF
server {
    listen 80;
    server_name $DOMAIN_NAME;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN_NAME;
    
    # SSL configuration (Cloudflare handles SSL termination)
    ssl_certificate /etc/ssl/certs/ssl-cert-snakeoil.pem;
    ssl_certificate_key /etc/ssl/private/ssl-cert-snakeoil.key;
    
    # Proxy to Flask app
    location / {
        proxy_pass http://127.0.0.1:${WEBSITE_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
    }
    
    # Static files
    location /static {
        alias $WORKING_DIR/app/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:;" always;
    
    # File upload size
    client_max_body_size 10M;
    
    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/xml+rss application/json;
}
EOF
    else
        print_warning "Domain configuration not found in .env - using default Nginx config"
        # Fallback to default configuration
        sudo tee /etc/nginx/sites-available/${WEBSITE_NAME} > /dev/null << EOF
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:${WEBSITE_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location /static {
        alias $WORKING_DIR/app/static;
    }
    client_max_body_size 10M;
}
EOF
    fi

    sudo ln -sf /etc/nginx/sites-available/${WEBSITE_NAME} /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default
    
    # Test Nginx configuration (sites-enabled is included via server_bootstrap → conf.d/00-sites-enabled.conf)
    sudo nginx -t
    sudo systemctl enable --now nginx 2>/dev/null || true
    sudo systemctl reload nginx 2>/dev/null || sudo systemctl restart nginx

    # Reload systemd and start app + tunnel services
    print_status "Starting services..."
    sudo systemctl daemon-reload
    # Quadlet unit naming can vary by host; detect and use the available unit.
    WEBSITE_CONTAINER_UNIT=""
    for candidate in "${WEBSITE_NAME}.service" "${WEBSITE_NAME}-container.service" "container-${WEBSITE_NAME}.service"; do
        if sudo systemctl list-unit-files "$candidate" --no-legend 2>/dev/null | grep -Eq "^${candidate}[[:space:]]"; then
            WEBSITE_CONTAINER_UNIT="$candidate"
            break
        fi
    done

    if [ -n "$WEBSITE_CONTAINER_UNIT" ]; then
        if ! sudo systemctl enable "$WEBSITE_CONTAINER_UNIT" 2>/dev/null; then
            print_warning "Could not enable $WEBSITE_CONTAINER_UNIT (generated/transient on this host)."
            print_warning "The service will still be started now; verify boot persistence after reboot."
        fi
    else
        print_warning "No generated systemd unit found yet for ${WEBSITE_NAME} container."
        print_warning "Will attempt to start common unit names and continue."
    fi
    if [ "${HAS_CLOUDFLARE_TUNNEL:-0}" = "1" ]; then
        sudo systemctl enable cloudflared-${WEBSITE_NAME}
    fi

    if [ -n "$WEBSITE_CONTAINER_UNIT" ]; then
        if ! sudo systemctl start "$WEBSITE_CONTAINER_UNIT"; then
            print_warning "Could not start $WEBSITE_CONTAINER_UNIT; continuing setup."
        fi
    else
        sudo systemctl start "${WEBSITE_NAME}.service" 2>/dev/null || \
        sudo systemctl start "${WEBSITE_NAME}-container.service" 2>/dev/null || \
        sudo systemctl start "container-${WEBSITE_NAME}.service" 2>/dev/null || \
        print_warning "Could not start container service for ${WEBSITE_NAME}; continuing setup."
    fi
    if [ "${HAS_CLOUDFLARE_TUNNEL:-0}" = "1" ]; then
        sudo systemctl start cloudflared-${WEBSITE_NAME}
    fi

    WEBSERVER_ETC="${WEBSERVER_ETC:-/etc/webserver}"
    SYNC_SCRIPT="${WEBSERVER_ETC}/sync_postgres_app_passwords.sh"
    if [ -x "$SYNC_SCRIPT" ]; then
        print_status "Syncing Postgres role/password from .env (idempotent)..."
        sudo "$SYNC_SCRIPT" "$WORKING_DIR" || print_warning "Postgres sync failed — run: sudo $SYNC_SCRIPT $WORKING_DIR"
    else
        print_warning "Postgres sync script missing — re-run server_bootstrap.sh or install $SYNC_SCRIPT"
    fi

    print_status "Host hardening (SELinux booleans, SSH, dnf-automatic, fail2ban, firewalld) is applied by server_bootstrap.sh"
    print_status "Security snapshot: SELinux=$(getenforce 2>/dev/null || echo '?') fail2ban=$(systemctl is-active fail2ban 2>/dev/null || echo '?') firewalld=$(systemctl is-active firewalld 2>/dev/null || echo '?')"
fi

# Fix ownership of all files created during setup (container may leave root-owned files on the bind mount;
# when this script is not invoked as root, chown requires sudo).
print_status "Fixing file ownership..."
if [ "$(id -u)" -eq 0 ]; then
    chown -R "$SERVICE_USER:$SERVICE_USER" "$WORKING_DIR"
    chmod -R 755 "$WORKING_DIR"
    chmod 600 "$WORKING_DIR/.env"
else
    sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$WORKING_DIR"
    sudo chmod -R 755 "$WORKING_DIR"
    sudo chmod 600 "$WORKING_DIR/.env"
fi

# Final status messages
print_status "Setup completed successfully!"

if [ "$IS_PRODUCTION" = true ]; then
    DOMAIN_NAME=$(grep "^DOMAIN_NAME=" "$WORKING_DIR/.env" | cut -d'=' -f2 | tr -d ' ')
    TUNNEL_ID=$(grep "^CLOUDFLARE_TUNNEL_ID=" "$WORKING_DIR/.env" | cut -d'=' -f2 | tr -d ' ')
    
    print_warning "Please make sure to:"
    if cloudflare_tunnel_skipped_via_env "$WORKING_DIR/.env"; then
        print_warning "1. Cloudflare tunnel skipped (SKIP_CLOUDFLARE_TUNNEL in .env) — no tunnel CNAME checklist."
        print_warning "2. DB backup: sudo crontab -l (default 02:00 — BACKUP_CRON_SCHEDULE to change)"
        print_warning "3. Root cron: sudo crontab -l (cloudflared / DDNS from server_bootstrap if used on this host)"
        print_warning ""
        if [ -n "$DOMAIN_NAME" ] && [ "$DOMAIN_NAME" != "your_domain_here" ]; then
            print_warning "Public hostname (configure DNS/reverse-proxy as you prefer): https://${DOMAIN_NAME}"
        fi
    elif [ -n "$TUNNEL_ID" ] && [ "$TUNNEL_ID" != "your_tunnel_id_here" ]; then
        # For logs.brakesystems.ca → apex brakesystems.ca, relative name logs (not another zone on the account).
        DNS_APEX="${DOMAIN_NAME#*.}"
        DNS_REL="${DOMAIN_NAME%.$DNS_APEX}"
        print_warning "1. Cloudflare DNS for this app (dedicated tunnel ${WEBSITE_NAME}-tunnel):"
        print_warning "   In the DNS zone for ${DNS_APEX} (e.g. brakesystems.ca subdomains), add manually a proxied CNAME or Tunnel record:"
        print_warning "   Name: ${DNS_REL}   Target: ${TUNNEL_ID}.cfargotunnel.com"
        print_warning "   (Other subdomains may point at a different tunnel; this hostname must use this tunnel ID.)"
        print_warning "   cloudflared tunnel route dns can attach to the wrong zone if the account has multiple zones — prefer manual DNS in the intended zone."
        print_warning "2. Set Cloudflare SSL/TLS mode to 'Full (strict)'"
        print_warning "3. DB backup: sudo crontab -l (default 02:00 — BACKUP_CRON_SCHEDULE to change)"
        print_warning "4. Root cron: sudo crontab -l (cloudflared: /etc/webserver/update_cloudflared.sh; DDNS/reboot from server_bootstrap)"
        print_warning ""
        print_warning "Your app will be available at: https://${DOMAIN_NAME}"
    else
        print_warning "1. Configure Cloudflare tunnel in .env file:"
        print_warning "   - CLOUDFLARE_TUNNEL_ID"
        print_warning "   - CLOUDFLARE_ACCOUNT_TAG"
        print_warning "   - CLOUDFLARE_TUNNEL_SECRET"
        print_warning "   (or set SKIP_CLOUDFLARE_TUNNEL=true to run production without a tunnel)"
        print_warning "2. Set up domain configuration:"
        print_warning "   - DOMAIN_NAME"
        print_warning "3. DB backup: sudo crontab -l (default 02:00)"
        print_warning "4. Root cron: sudo crontab -l"
    fi
    print_warning ""
    print_warning "Database connection test:"
    print_warning "psql -h localhost -U $DB_USER -d $DB_NAME -c '\\dt'"
    print_warning ""
    print_warning "To test the app locally:"
    print_warning "cd $WORKING_DIR && source venv/bin/activate && python app.py"
    print_warning ""
else
    print_status "To start the development server:"
    print_status "cd $WORKING_DIR && source venv/bin/activate && python app.py"
    print_status ""
    print_status "Database connection test:"
    print_status "psql -h localhost -U $DB_USER -d $DB_NAME -c '\\dt'"
    print_status ""
    print_status "Development server will run on: http://127.0.0.1:${WEBSITE_PORT}"
    print_status ""
fi

print_info "Template setup completed! Remember to:"
print_info "1. Update the configuration variables at the top of this script"
print_info "2. Customize the .env file for your specific website"
print_info "3. Test the setup before deploying to production"
print_info "4. Backup script created automatically: $BACKUP_SCRIPT"