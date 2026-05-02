#!/bin/bash

# Initialize this template for a new project domain/port.
# Project slug = parent directory of deployment_items/ (name your project folder accordingly).
# Usage:
#   ./deployment_items/init_new_project.sh <domain> <port>
# Example (from a project folder named my_new_site):
#   ./deployment_items/init_new_project.sh mynewsite.com 5060

set -euo pipefail

DOMAIN="${1:-}"
PORT="${2:-}"

WORKING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_SLUG="$(basename "${WORKING_DIR}")"

if [ -z "${DOMAIN}" ] || [ -z "${PORT}" ]; then
    echo "Usage: $0 <domain> <port>"
    echo "  Slug is taken from the project directory name: $(basename "${WORKING_DIR}")"
    echo "Example (run from project root): $0 mynewsite.com 5060"
    exit 1
fi

if [ "${PROJECT_SLUG}" = "project_template_containerized" ]; then
    echo "[!] Warning: slug is still \"project_template_containerized\"."
    echo "    Copy this template into a new folder named for your site, cd there, then run this script."
fi

echo "[+] Initializing template in: ${WORKING_DIR}"
echo "[+] Project slug (from directory name): ${PROJECT_SLUG}"
echo "[+] Domain: ${DOMAIN}"
echo "[+] Port: ${PORT}"

# Replace template placeholders across project files (no legacy product names).
# teardown_site.sh: do not global-replace work_logs — that would break the guard
# `if [ "$WEBSITE_NAME" = "work_logs" ]` (must stay literal). Only substitute the
# WEBSITE_NAME= assignment line.
while IFS= read -r file; do
    [ -f "${file}" ] || continue
    base="$(basename "${file}")"
    if [ "${base}" = "teardown_site.sh" ]; then
        sed -i "s/yourdomain\\.com/${DOMAIN}/g" "${file}"
        sed -i "s/PORT=5054/PORT=${PORT}/g" "${file}"
        sed -i "s/WEBSITE_PORT=\"5050\"/WEBSITE_PORT=\"${PORT}\"/g" "${file}"
        sed -i "s/^WEBSITE_NAME=\"work_logs\"/WEBSITE_NAME=\"${PROJECT_SLUG}\"/" "${file}"
    else
        sed -i "s/work_logs/${PROJECT_SLUG}/g" "${file}"
        sed -i "s/yourdomain\\.com/${DOMAIN}/g" "${file}"
        sed -i "s/PORT=5054/PORT=${PORT}/g" "${file}"
        sed -i "s/WEBSITE_PORT=\"5050\"/WEBSITE_PORT=\"${PORT}\"/g" "${file}"
    fi
done < <(grep -RIlE "work_logs|yourdomain\\.com|PORT=5054|WEBSITE_PORT=\"5050\"" "${WORKING_DIR}")

# Rename generic setup script to <slug>_setup.sh for this project
if [ -f "${WORKING_DIR}/deployment_items/website_setup.sh" ]; then
    mv "${WORKING_DIR}/deployment_items/website_setup.sh" "${WORKING_DIR}/deployment_items/${PROJECT_SLUG}_setup.sh"
fi

# Rename generic teardown script to <slug>_teardown.sh (values already substituted by the loop above)
if [ -f "${WORKING_DIR}/deployment_items/teardown_site.sh" ]; then
    mv "${WORKING_DIR}/deployment_items/teardown_site.sh" "${WORKING_DIR}/deployment_items/${PROJECT_SLUG}_teardown.sh"
    chmod +x "${WORKING_DIR}/deployment_items/${PROJECT_SLUG}_teardown.sh"
fi

echo "[+] Initialization complete."
echo "[+] Next steps:"
echo "    1) Run ./deployment_items/${PROJECT_SLUG}_setup.sh to create .env on first run."
echo "    2) Review .env values (create from .env.example if needed)."
echo "    3) Run ./deployment_items/${PROJECT_SLUG}_setup.sh again to finish setup."
