#!/usr/bin/env bash
# Deploy the plugin, vendored VT and SmartPI and the simulator to the test Home Assistant in the
# dedicated test LXC, then (re)start it (docs/plan-0.2.md, J1).
#
# Usage: scripts/deploy_test.sh [--dry-run]
#
# Everything is packed here into one tar stream — links followed, so the host receives files,
# never links into vendor/ — and unpacked there over SSH: only tar and ssh are needed on either
# side. --dry-run packs the same stream and lists it; it reads no key and connects nowhere.
#
# It connects only to TEST_HA_HOST from devenv/local.env, with the key and known hosts kept in
# devenv/ssh/ (both git-ignored), so nothing in the home directory changes. It never touches
# any other Home Assistant.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/devenv/local.env"
SSH_DIR="$ROOT/devenv/ssh"

DRY_RUN=false
case "${1:-}" in
    "") ;;
    --dry-run) DRY_RUN=true ;;
    *)
        echo "usage: scripts/deploy_test.sh [--dry-run]" >&2
        exit 2
        ;;
esac

for needed in "$ROOT/vendor/custom_components/versatile_thermostat" \
              "$ROOT/vendor/custom_components/vtherm_smartpi"; do
    if [ ! -d "$needed" ]; then
        echo "$needed is missing: vendor/ is not set up." >&2
        exit 1
    fi
done

# The directory on the host mirrors the stream: compose.yaml, config/configuration.yaml (the
# rest of config/ belongs to the running instance) and the four integrations, which compose.yaml
# mounts read-only.
COMPONENTS=(vtherm_smart_boiler versatile_thermostat vtherm_smartpi boiler_sim)
pack() {
    tar -c -f - --dereference --exclude __pycache__ --exclude '*.pyc' \
        -C "$ROOT/devenv" compose.yaml config/configuration.yaml \
        -C "$ROOT" custom_components/vtherm_smart_boiler \
        -C "$ROOT/vendor" custom_components/versatile_thermostat custom_components/vtherm_smartpi \
        -C "$ROOT/sim" custom_components/boiler_sim
}

# Only devenv/local.env says where to go: nothing from the calling environment.
unset TEST_HA_HOST TEST_HA_SSH_USER TEST_HA_DIR TEST_HA_URL TEST_HA_TOKEN TZ
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

if [ "$DRY_RUN" = true ]; then
    echo "Would deploy to ${TEST_HA_HOST:-<TEST_HA_HOST, not set>}:${TEST_HA_DIR:-<TEST_HA_DIR, not set>}:"
    pack | tar -t -v -f -
    exit 0
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "devenv/local.env is missing: copy devenv/local.env.example and fill it in." >&2
    exit 1
fi
: "${TEST_HA_HOST:?TEST_HA_HOST is empty in devenv/local.env}"
: "${TEST_HA_SSH_USER:?TEST_HA_SSH_USER is empty in devenv/local.env}"
: "${TEST_HA_DIR:?TEST_HA_DIR is empty in devenv/local.env}"
# The deploy replaces directories under TEST_HA_DIR: never a top-level directory or a relative one.
case "$TEST_HA_DIR" in
    /*/*) ;;
    *)
        echo "TEST_HA_DIR must be an absolute path below a top-level directory." >&2
        exit 1
        ;;
esac
case "$TEST_HA_DIR${TZ:-}" in
    *"'"*)
        echo "TEST_HA_DIR and TZ must not contain a quote." >&2
        exit 1
        ;;
esac
KEY="$SSH_DIR/id_ed25519"
if [ ! -f "$KEY" ]; then
    echo "devenv/ssh/id_ed25519 is missing (see devenv/README.md)." >&2
    exit 1
fi

# No ssh configuration but these options: ~/.ssh/config and /etc/ssh/ssh_config could change
# where and how it connects (a Host alias, ProxyJump, another identity, a shared connection).
SSH=(ssh -F /dev/null -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes
     -o ControlMaster=no -o ControlPath=none
     -o "UserKnownHostsFile=$SSH_DIR/known_hosts" -o GlobalKnownHostsFile=/dev/null
     -o StrictHostKeyChecking=accept-new "$TEST_HA_SSH_USER@$TEST_HA_HOST")

# Unpacked into a fresh directory first; each integration then replaces its old copy whole, so
# nothing removed here stays behind there.
pack | "${SSH[@]}" "set -eu
cd '$TEST_HA_DIR' 2>/dev/null || { mkdir -p '$TEST_HA_DIR' && cd '$TEST_HA_DIR'; }
rm -rf .incoming && mkdir .incoming && tar -x -f - -C .incoming
mkdir -p config custom_components
mv .incoming/compose.yaml compose.yaml
mv .incoming/config/configuration.yaml config/configuration.yaml
for component in ${COMPONENTS[*]}; do
    rm -rf \"custom_components/\$component\"
    mv \".incoming/custom_components/\$component\" \"custom_components/\$component\"
done
rm -rf .incoming
TZ='${TZ:-UTC}' docker compose up -d
docker compose restart homeassistant"
echo "Deployed to $TEST_HA_HOST; Home Assistant is restarting."
