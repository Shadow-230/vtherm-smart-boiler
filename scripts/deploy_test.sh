#!/usr/bin/env bash
# Deploy the plugin, vendored VT and SmartPI and the simulator to the test Home Assistant in the
# dedicated test LXC, then (re)start it (docs/plan-0.2.md, J1).
#
# Usage: scripts/deploy_test.sh [--dry-run]
#
# It connects only to TEST_HA_HOST from devenv/local.env, with the key and known hosts kept in
# devenv/ssh/ (both git-ignored), so nothing in the home directory changes. It never touches
# any other Home Assistant.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/devenv/local.env"
SSH_DIR="$ROOT/devenv/ssh"

if [ ! -f "$ENV_FILE" ]; then
    echo "devenv/local.env is missing: copy devenv/local.env.example and fill it in." >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${TEST_HA_HOST:?TEST_HA_HOST is empty in devenv/local.env}"
: "${TEST_HA_SSH_USER:?TEST_HA_SSH_USER is empty in devenv/local.env}"
: "${TEST_HA_DIR:?TEST_HA_DIR is empty in devenv/local.env}"
KEY="$SSH_DIR/id_ed25519"
if [ ! -f "$KEY" ]; then
    echo "devenv/ssh/id_ed25519 is missing (see devenv/README.md)." >&2
    exit 1
fi
for needed in "$ROOT/vendor/custom_components/versatile_thermostat" \
              "$ROOT/vendor/custom_components/vtherm_smartpi"; do
    if [ ! -d "$needed" ]; then
        echo "$needed is missing: vendor/ is not set up." >&2
        exit 1
    fi
done

DRY=()
if [ "${1:-}" = "--dry-run" ]; then
    DRY=(--dry-run)
fi

SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o "UserKnownHostsFile=$SSH_DIR/known_hosts"
     -o StrictHostKeyChecking=accept-new)
TARGET="$TEST_HA_SSH_USER@$TEST_HA_HOST"
RSYNC=(rsync -a --delete --exclude __pycache__ --exclude '*.pyc' "${DRY[@]}" -e "${SSH[*]}")

"${SSH[@]}" "$TARGET" "mkdir -p '$TEST_HA_DIR/config' '$TEST_HA_DIR/plugin/vendor/custom_components' '$TEST_HA_DIR/plugin/custom_components'"
"${RSYNC[@]}" "$ROOT/devenv/compose.yaml" "$TARGET:$TEST_HA_DIR/compose.yaml"
# configuration.yaml only: the rest of config/ belongs to the running instance.
"${RSYNC[@]}" "$ROOT/devenv/config/configuration.yaml" "$TARGET:$TEST_HA_DIR/config/configuration.yaml"
"${RSYNC[@]}" "$ROOT/custom_components/vtherm_smart_boiler" "$TARGET:$TEST_HA_DIR/plugin/custom_components/"
"${RSYNC[@]}" "$ROOT/vendor/custom_components/versatile_thermostat" \
              "$ROOT/vendor/custom_components/vtherm_smartpi" \
              "$TARGET:$TEST_HA_DIR/plugin/vendor/custom_components/"
"${RSYNC[@]}" --exclude custom_components/boiler_sim/__pycache__ "$ROOT/sim" "$TARGET:$TEST_HA_DIR/plugin/"

if [ "${#DRY[@]}" -eq 0 ]; then
    "${SSH[@]}" "$TARGET" "cd '$TEST_HA_DIR' && TZ='${TZ:-UTC}' docker compose up -d && docker compose restart homeassistant"
    echo "Deployed to $TEST_HA_HOST; Home Assistant is restarting."
fi
