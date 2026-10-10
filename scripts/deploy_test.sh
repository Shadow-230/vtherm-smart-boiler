#!/usr/bin/env bash
# Deploy the plugin, vendored VT and SmartPI and the simulator to the test Home Assistant in the
# dedicated test LXC, then (re)start it (docs/plan-0.2.md, J1).
#
# Usage: scripts/deploy_test.sh [--dry-run] [--instance 1-8] [--config NAME]
#
# Everything is packed here into one tar stream — links followed, so the host receives files,
# never links into vendor/ — and unpacked there over SSH: only tar and ssh are needed on either
# side. --dry-run packs the same stream and lists it; it reads no key, no devenv/local.env, and
# connects nowhere.
#
# Up to eight test instances can run side by side in the same LXC, so long scenarios run in
# parallel. --instance N picks one: 1, the default, is TEST_HA_DIR, container ha-test, port
# 8123; N = 2 to 8 is TEST_HA_DIR_N, container ha-test-N, port 8122 + N. Each has its own
# directory, marker, configuration and Home Assistant; the stream is the same.
#
# --config NAME sends devenv/config/NAME.yaml as the instance's configuration.yaml instead of
# devenv/config/configuration.yaml — for example starts.yaml, J4's starts criterion.
#
# It connects only to TEST_HA_HOST from devenv/local.env, with the key and known hosts kept in
# devenv/ssh/ (both git-ignored), so nothing in the home directory changes. It never touches
# any other Home Assistant.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/devenv/local.env"
SSH_DIR="$ROOT/devenv/ssh"

DRY_RUN=false
INSTANCE=1
CONFIG=configuration
usage() {
    echo "usage: scripts/deploy_test.sh [--dry-run] [--instance 1-8] [--config NAME]" >&2
    exit 2
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --instance)
            case "${2:-}" in
                [1-8]) INSTANCE="$2" ;;
                *) usage ;;
            esac
            shift
            ;;
        --config)
            case "${2:-}" in
                "" | *[!a-z0-9_-]*) usage ;;
                *) CONFIG="$2" ;;
            esac
            shift
            ;;
        *) usage ;;
    esac
    shift
done
if [ ! -f "$ROOT/devenv/config/$CONFIG.yaml" ]; then
    echo "devenv/config/$CONFIG.yaml does not exist." >&2
    exit 1
fi
if [ "$INSTANCE" = 1 ]; then
    CONTAINER=ha-test
    DIR_VAR=TEST_HA_DIR
else
    CONTAINER="ha-test-$INSTANCE"
    DIR_VAR="TEST_HA_DIR_$INSTANCE"
fi
PORT=$((8122 + INSTANCE))

for needed in "$ROOT/vendor/custom_components/versatile_thermostat" \
              "$ROOT/vendor/custom_components/vtherm_smartpi"; do
    if [ ! -d "$needed" ]; then
        echo "$needed is missing: vendor/ is not set up." >&2
        exit 1
    fi
done

# The directory on the host mirrors the stream: compose.yaml, config/configuration.yaml (the
# rest of config/ belongs to the running instance) and the six integrations, which compose.yaml
# mounts read-only — among them the test-only stub "opentherm_gw" on the simulator, which
# overrides Home Assistant's own OpenTherm Gateway integration there, and only there (P-37).
COMPONENTS=(vtherm_smart_boiler versatile_thermostat vtherm_smartpi boiler_sim opentherm_gw j4_faults)
pack() {
    tar -c -f - --dereference --exclude __pycache__ --exclude '*.pyc' \
        --transform "s,^config/$CONFIG\\.yaml\$,config/configuration.yaml," \
        -C "$ROOT/devenv" compose.yaml "config/$CONFIG.yaml" \
        -C "$ROOT" custom_components/vtherm_smart_boiler \
        -C "$ROOT/vendor" custom_components/versatile_thermostat custom_components/vtherm_smartpi \
        -C "$ROOT/sim" custom_components/boiler_sim custom_components/opentherm_gw \
        custom_components/j4_faults
}

# The dry run reads nothing private (P-107): devenv/local.env is not even sourced.
if [ "$DRY_RUN" = true ]; then
    if [ "$INSTANCE" = 1 ]; then
        echo "Would deploy to the test HA named in devenv/local.env:"
    else
        echo "Would deploy to test instance $INSTANCE named in devenv/local.env (port $PORT):"
    fi
    pack | tar -t -v -f -
    exit 0
fi

# Only devenv/local.env says where to go: nothing from the calling environment.
unset TEST_HA_HOST TEST_HA_SSH_USER TEST_HA_DIR TEST_HA_URL TEST_HA_TOKEN TZ
unset TEST_HA_DIR_2 TEST_HA_URL_2 TEST_HA_TOKEN_2 TEST_HA_DIR_3 TEST_HA_URL_3 TEST_HA_TOKEN_3
unset TEST_HA_DIR_4 TEST_HA_URL_4 TEST_HA_TOKEN_4 TEST_HA_DIR_5 TEST_HA_URL_5 TEST_HA_TOKEN_5
unset TEST_HA_DIR_6 TEST_HA_URL_6 TEST_HA_TOKEN_6 TEST_HA_DIR_7 TEST_HA_URL_7 TEST_HA_TOKEN_7
unset TEST_HA_DIR_8 TEST_HA_URL_8 TEST_HA_TOKEN_8
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "devenv/local.env is missing: copy devenv/local.env.example and fill it in." >&2
    exit 1
fi
: "${TEST_HA_HOST:?TEST_HA_HOST is empty in devenv/local.env}"
: "${TEST_HA_SSH_USER:?TEST_HA_SSH_USER is empty in devenv/local.env}"
: "${TEST_HA_DIR:?TEST_HA_DIR is empty in devenv/local.env}"
CHOSEN="${!DIR_VAR:-}"
if [ -z "$CHOSEN" ]; then
    echo "$DIR_VAR is empty in devenv/local.env (test instance $INSTANCE)." >&2
    exit 1
fi
# Each instance has a directory of its own: never another's, which the deploy would overwrite.
for other in TEST_HA_DIR TEST_HA_DIR_2 TEST_HA_DIR_3 TEST_HA_DIR_4 TEST_HA_DIR_5 TEST_HA_DIR_6 \
    TEST_HA_DIR_7 TEST_HA_DIR_8; do
    if [ "$other" != "$DIR_VAR" ] && [ -n "${!other:-}" ] && [ "${!other%/}" = "${CHOSEN%/}" ]; then
        echo "$DIR_VAR must not be $other: each instance has its own directory." >&2
        exit 1
    fi
done
TEST_HA_DIR="$CHOSEN"
# The deploy replaces directories under TEST_HA_DIR: never a top-level directory or a relative
# one, and nothing that only looks deeper — no "." or ".." component, no "//", no trailing slash
# (PB-87: "/opt/.." is "/"), and only plain path characters.
case "$TEST_HA_DIR" in
    /*/*) ;;
    *)
        echo "TEST_HA_DIR must be an absolute path below a top-level directory." >&2
        exit 1
        ;;
esac
case "$TEST_HA_DIR/" in
    *//* | */./* | */../* | *[!A-Za-z0-9._/-]*)
        echo "TEST_HA_DIR must be a plain absolute path: no '.' or '..' component, no '//'," \
            "no trailing slash, only letters, digits, '.', '_', '-' and '/'." >&2
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

# Nothing is replaced and Home Assistant is not restarted unless the host shows it is the test
# LXC: the user creates the marker file in TEST_HA_DIR there at J2 (PB-87; devenv/README.md). A
# missing directory is not created. Then everything is unpacked into a fresh directory first;
# each integration replaces its old copy whole, so nothing removed here stays behind there.
MARKER=.vtherm-smart-boiler-test-ha
pack | "${SSH[@]}" "set -eu
cd '$TEST_HA_DIR'
if [ ! -f '$MARKER' ]; then
    echo 'No $MARKER in $TEST_HA_DIR on this host: not the test LXC, nothing changed.' >&2
    exit 3
fi
rm -rf .incoming && mkdir .incoming && tar -x -f - -C .incoming
mkdir -p config custom_components
mv .incoming/compose.yaml compose.yaml
mv .incoming/config/configuration.yaml config/configuration.yaml
for component in ${COMPONENTS[*]}; do
    rm -rf \"custom_components/\$component\"
    mv \".incoming/custom_components/\$component\" \"custom_components/\$component\"
done
rm -rf .incoming
printf 'HA_CONTAINER=%s\nHA_PORT=%s\nTZ=%s\n' '$CONTAINER' '$PORT' '${TZ:-UTC}' > .env
docker compose up -d
docker compose restart homeassistant"
echo "Deployed to $TEST_HA_HOST (container $CONTAINER, port $PORT); Home Assistant is restarting."
