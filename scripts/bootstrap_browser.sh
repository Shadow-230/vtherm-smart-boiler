#!/usr/bin/env bash
# Put a headless Chromium into .tools/ for the Boiler page's screenshots
# (docs/en/development/plans/plan-0.2-i10.md; the user's consent of 2026-11-18): Playwright's own
# Chromium build into .tools/ms-playwright, and the system libraries it needs that a host without a
# desktop lacks — Debian packages fetched with `apt-get download` (no root; apt checks them against
# Debian's signed lists) and unpacked into .tools/chromium-libs, used only by the screenshot tool.
# Nothing is installed into the system. Needs scripts/bootstrap_node.sh and `npm ci` in frontend/.
#
# Usage: scripts/bootstrap_browser.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIBS="$ROOT/.tools/chromium-libs"
# What Chromium's headless shell needs beyond a minimal Debian 12, found with ldd.
PACKAGES=(
    libglib2.0-0 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libxcomposite1 libxdamage1
    libxfixes3 libxrandr2 libgbm1 libxkbcommon0 libasound2 libdrm2 libwayland-server0 libxi6
)

"$ROOT/scripts/env.sh" npx --prefix "$ROOT/frontend" playwright install --only-shell chromium

if command -v apt-get >/dev/null && command -v dpkg-deb >/dev/null; then
    mkdir -p "$ROOT/.tmp"
    WORK="$(mktemp -d "$ROOT/.tmp/debs.XXXXXX")"
    trap 'rm -rf "$WORK"' EXIT
    (cd "$WORK" && apt-get download "${PACKAGES[@]}")
    mkdir -p "$LIBS"
    for deb in "$WORK"/*.deb; do
        dpkg-deb -x "$deb" "$LIBS"
    done
    echo "Chromium's libraries are in .tools/chromium-libs"
else
    echo "No apt-get here: Chromium uses the system's own libraries"
fi
