#!/bin/bash
#
# Generic teardown: remove one site from this host (inverse of *_setup.sh patterns).
# In the template this file is teardown_site.sh; init_new_project.sh renames it to
# <slug>_teardown.sh (same pattern as website_setup.sh → <slug>_setup.sh).
# WORKING_DIR is the parent of deployment_items/.
#
# Edit WEBSITE_NAME and WEBSITE_PORT below to match the values at the top of your *_setup.sh.
#
# Does NOT remove: web-postgres / web-redis containers, shared nginx include, cloudflared
# binary, /etc/webserver/update_cloudflared.sh, root's cloudflared-update crontab line,
# ~/.cloudflared/cert.pem, or other sites' configs.
#
# DB removal follows FLASK_ENV in .env (same as website_setup.sh): production → drop in
# web-postgres; otherwise → drop on host postgresql when that service is active. Podman/systemd
# steps are no-ops when those resources were never created (e.g. dev PC without containers).
#
# Usage (from project root, as a user with sudo). Before init: teardown_site.sh; after
# init_new_project.sh: ./deployment_items/<slug>_teardown.sh
#   sudo ./deployment_items/teardown_site.sh
#   sudo ./deployment_items/teardown_site.sh --yes
# Optional:
#   --remove-backups   also remove ~/backups/${WEBSITE_NAME} (run with sudo so root-owned backup files delete cleanly)
#   --remove-project   also rm -rf the project working directory (DESTRUCTIVE)
#   -h, --help         show this header
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
info() { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err() { echo -e "${RED}[-]${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKING_DIR="$(dirname "$SCRIPT_DIR")"

# ---------------------------------------------------------------------------
# Configuration — must match your *_setup.sh for this project
# (init_new_project.sh replaces your_project_name / port when you use the template.)
# ---------------------------------------------------------------------------
WEBSITE_NAME="work_logs" # e.g. brake_systems_logs, math_basics
WEBSITE_PORT="5054"              # keep in sync with WEBSITE_PORT in *_setup.sh

DB_NAME="${WEBSITE_NAME}_db"
DB_USER="${WEBSITE_NAME}_user"
BACKUP_SCRIPT="backup_${WEBSITE_NAME}"

if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    SERVICE_USER="$SUDO_USER"
elif [ -d "$WORKING_DIR" ]; then
    SERVICE_USER="$(stat -c '%U' "$WORKING_DIR" 2>/dev/null || true)"
    [ -z "$SERVICE_USER" ] || [ "$SERVICE_USER" = "root" ] && SERVICE_USER="$(id -un)"
else
    SERVICE_USER="$(id -un)"
fi
SERVICE_USER_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"

# DB teardown mirrors website_setup.sh: production → web-postgres; development → host postgresql.
drop_db_in_web_postgres() {
    local super="$1"
    info "Dropping database ${DB_NAME} and role ${DB_USER} in web-postgres..."
    set +e
    podman exec -i web-postgres env PGPASSWORD="${super}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<EOSQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS ${DB_NAME};
DROP ROLE IF EXISTS ${DB_USER};
EOSQL
    local db_rc=$?
    set -e
    if [ "$db_rc" != "0" ]; then
        warn "First DB/role drop attempt failed (rc=$db_rc); trying REASSIGN OWNED / DROP OWNED..."
        podman exec -i web-postgres env PGPASSWORD="${super}" psql -U postgres -d postgres <<EOSQL2 || true
REASSIGN OWNED BY ${DB_USER} TO postgres;
DROP OWNED BY ${DB_USER};
DROP ROLE IF EXISTS ${DB_USER};
EOSQL2
    fi
    info "Postgres cleanup finished for ${DB_NAME} / ${DB_USER} (verify in psql if unsure)."
}

drop_db_on_host_postgresql() {
    info "Dropping database ${DB_NAME} and role ${DB_USER} on host PostgreSQL (development)..."
    set +e
    sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 <<EOSQLH
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS ${DB_NAME};
DROP ROLE IF EXISTS ${DB_USER};
EOSQLH
    local db_rc=$?
    set -e
    if [ "$db_rc" != "0" ]; then
        warn "First host DB/role drop attempt failed (rc=$db_rc); trying REASSIGN OWNED / DROP OWNED..."
        sudo -u postgres psql -d postgres <<EOSQLH2 || true
REASSIGN OWNED BY ${DB_USER} TO postgres;
DROP OWNED BY ${DB_USER};
DROP ROLE IF EXISTS ${DB_USER};
EOSQLH2
    fi
    info "Host Postgres cleanup finished for ${DB_NAME} / ${DB_USER}."
}

YES=0
REMOVE_BACKUPS=0
REMOVE_PROJECT=0
for arg in "$@"; do
    case "$arg" in
        --yes) YES=1 ;;
        --remove-backups) REMOVE_BACKUPS=1 ;;
        --remove-project) REMOVE_PROJECT=1 ;;
        -h|--help)
            grep '^#' "$0" | head -n 22
            exit 0
            ;;
        *)
            err "Unknown option: $arg"
            exit 1
            ;;
    esac
done

# Literal your_project_name must stay in sync with init_new_project.sh (assignment line only is substituted).
if [ "$WEBSITE_NAME" = "your_project_name" ]; then
    err "Set WEBSITE_NAME at the top of this script (or run init_new_project.sh) before running teardown."
    exit 1
fi

info "Teardown for WEBSITE_NAME=$WEBSITE_NAME"
info "WORKING_DIR=$WORKING_DIR SERVICE_USER=$SERVICE_USER"

if [ "$YES" != "1" ]; then
    warn "This stops/disables site services (no-op if units/containers were never created), drops DB ${DB_NAME}"
    warn "(web-postgres when FLASK_ENV=production in .env; host postgresql otherwise), removes nginx vhost,"
    warn "backup cron line, site cloudflared files, Quadlet unit, and Podman container/image when present."
    read -r -p "Type yes to continue: " confirm
    if [ "$confirm" != "yes" ]; then
        info "Aborted."
        exit 0
    fi
fi

if [ "$(id -u)" -ne 0 ]; then
    err "Run with sudo so systemd, nginx, podman, and root crontab can be updated."
    exit 1
fi

for u in "cloudflared-${WEBSITE_NAME}" "${WEBSITE_NAME}" "${WEBSITE_NAME}-container" "container-${WEBSITE_NAME}"; do
    systemctl disable --now "${u}.service" 2>/dev/null || true
done

podman rm -f "${WEBSITE_NAME}" 2>/dev/null || true

rm -f "/etc/systemd/system/cloudflared-${WEBSITE_NAME}.service"
rm -f "/etc/containers/systemd/${WEBSITE_NAME}.container"
rm -f "/etc/systemd/system/${WEBSITE_NAME}.service"

podman rmi -f "localhost/${WEBSITE_NAME}:latest" "${WEBSITE_NAME}:latest" 2>/dev/null || true

systemctl daemon-reload || true
systemctl reset-failed 2>/dev/null || true
info "Stopped services and removed systemd/Quadlet units for ${WEBSITE_NAME}."

FLASK_ENV=""
if [ -f "${WORKING_DIR}/.env" ]; then
    FLASK_ENV="$(grep '^FLASK_ENV=' "${WORKING_DIR}/.env" 2>/dev/null | head -n1 | cut -d'=' -f2- | tr -d ' \t\r' || true)"
fi
PG_SUPER="$(cat /etc/webserver/postgres_superuser_password 2>/dev/null || true)"

if [ "$FLASK_ENV" = "production" ]; then
    if [ -z "$PG_SUPER" ]; then
        warn "Skipping DB drop (production): /etc/webserver/postgres_superuser_password not readable."
    elif ! command -v podman >/dev/null 2>&1 || ! podman container exists web-postgres 2>/dev/null; then
        warn "Skipping DB drop (production): podman or web-postgres container not available on this host."
    else
        drop_db_in_web_postgres "$PG_SUPER"
    fi
else
    # development (or FLASK_ENV unset / empty): same path as website_setup.sh host postgresql branch
    if systemctl is-active --quiet postgresql 2>/dev/null; then
        drop_db_on_host_postgresql
    elif [ -n "$PG_SUPER" ] && command -v podman >/dev/null 2>&1 && podman container exists web-postgres 2>/dev/null; then
        warn "FLASK_ENV is not production; web-postgres is present — dropping DB in container (unusual for dev)."
        drop_db_in_web_postgres "$PG_SUPER"
    else
        warn "Skipping DB drop: host postgresql is not active and web-postgres is not available (nothing to remove or install postgresql for dev)."
    fi
fi

if [ -L "/etc/nginx/sites-enabled/${WEBSITE_NAME}" ] || [ -f "/etc/nginx/sites-enabled/${WEBSITE_NAME}" ]; then
    rm -f "/etc/nginx/sites-enabled/${WEBSITE_NAME}"
    info "Removed /etc/nginx/sites-enabled/${WEBSITE_NAME}"
fi
if [ -f "/etc/nginx/sites-available/${WEBSITE_NAME}" ]; then
    rm -f "/etc/nginx/sites-available/${WEBSITE_NAME}"
    info "Removed /etc/nginx/sites-available/${WEBSITE_NAME}"
fi
if nginx -t 2>/dev/null; then
    systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
    info "Nginx configuration tested and reloaded."
else
    warn "nginx -t failed after removal — fix config manually before reloading nginx."
fi

CRON_LINE_PATH="${SCRIPT_DIR}/${BACKUP_SCRIPT}"
if crontab -l 2>/dev/null | grep -Fq "$CRON_LINE_PATH"; then
    crontab -l 2>/dev/null | grep -Fv "$CRON_LINE_PATH" | crontab -
    info "Removed root crontab line referencing ${CRON_LINE_PATH}"
else
    info "No root crontab line matched ${CRON_LINE_PATH} (nothing removed)."
fi

TUNNEL_ID=""
if [ -f "${WORKING_DIR}/.env" ]; then
    TUNNEL_ID="$(grep '^CLOUDFLARE_TUNNEL_ID=' "${WORKING_DIR}/.env" 2>/dev/null | head -n1 | sed 's/^CLOUDFLARE_TUNNEL_ID=//' | tr -d ' \t\r' || true)"
fi
CF_YML="${SERVICE_USER_HOME}/.cloudflared/${WEBSITE_NAME}-config.yml"
if [ -f "$CF_YML" ]; then
    rm -f "$CF_YML"
    info "Removed ${CF_YML}"
fi
if [ -n "$TUNNEL_ID" ] && [ "$TUNNEL_ID" != "your_tunnel_id_here" ]; then
    CF_JSON="${SERVICE_USER_HOME}/.cloudflared/${TUNNEL_ID}.json"
    if [ -f "$CF_JSON" ]; then
        rm -f "$CF_JSON"
        info "Removed tunnel credentials ${CF_JSON}"
    fi
fi

if [ "$REMOVE_BACKUPS" = "1" ]; then
    rm -rf "${SERVICE_USER_HOME}/backups/${WEBSITE_NAME}"
    info "Removed ${SERVICE_USER_HOME}/backups/${WEBSITE_NAME}"
fi

if [ "$REMOVE_PROJECT" = "1" ]; then
    warn "Removing project directory ${WORKING_DIR}"
    rm -rf "${WORKING_DIR}"
    info "Removed ${WORKING_DIR}"
fi

warn "Manual steps (not automated):"
echo "  1) Cloudflare: delete tunnel ${WEBSITE_NAME}-tunnel (or the tunnel UUID) in Zero Trust / Tunnels, and DNS if desired."
echo "  2) On the host: sudo -u ${SERVICE_USER} cloudflared tunnel delete ${WEBSITE_NAME}-tunnel"
echo "     (only if nothing else needs that tunnel name)."
echo "  3) If you removed the default nginx site earlier and need it back, restore your distro's default vhost manually."
echo "  4) Redis: default REDIS_DB=0 is often shared — do not FLUSHDB on production unless this site had a dedicated index."
echo ""
info "Teardown script finished."
