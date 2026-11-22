#!/usr/bin/env bash
# Put Node.js into .tools/node/ for building the Boiler page (docs/en/development/plans/plan-0.2-i10.md;
# the user's consent of 2026-11-18). The official archive from nodejs.org, checked against the
# SHA-256 written here — the one nodejs.org published for this release — so a changed download
# is refused. Nothing outside the project is touched.
#
# Usage: scripts/bootstrap_node.sh
set -euo pipefail

VERSION="v24.22.3" # LTS "Krypton", 2026-11-10; 26 needs libatomic, missing on some hosts

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/.tools/node"

if [ -x "$DEST/bin/node" ] && [ "$("$DEST/bin/node" --version)" = "$VERSION" ]; then
    echo "Node.js $VERSION is already in .tools/node"
    exit 0
fi

case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) PLATFORM="linux-x64" SHA256="4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb" ;;
    Linux-aarch64) PLATFORM="linux-arm64" SHA256="6e51a2ada00f0011cc266f65d98922b403d7ad88f809ca2aa615a5fe1ce6e86c" ;;
    Darwin-arm64) PLATFORM="darwin-arm64" SHA256="1d64136c8a43d648d1b3bad10797a4c995b1ca032d2bde8799de43b37f058fe5" ;;
    Darwin-x86_64) PLATFORM="darwin-x64" SHA256="4daeec962855c1a6e66cda398a25037319dc1bbd4a0939188b3547afbbfb6490" ;;
    *)
        echo "No Node.js archive is known here for $(uname -s) $(uname -m)" >&2
        exit 1
        ;;
esac

ARCHIVE="node-$VERSION-$PLATFORM.tar.xz"
mkdir -p "$ROOT/.tmp"
WORK="$(mktemp -d "$ROOT/.tmp/node.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

curl -fsSL "https://nodejs.org/dist/$VERSION/$ARCHIVE" -o "$WORK/$ARCHIVE"
if command -v sha256sum >/dev/null; then
    GOT="$(sha256sum "$WORK/$ARCHIVE" | cut -d' ' -f1)"
else
    GOT="$(shasum -a 256 "$WORK/$ARCHIVE" | cut -d' ' -f1)"
fi
if [ "$GOT" != "$SHA256" ]; then
    echo "The download's SHA-256 is $GOT, not $SHA256: refused" >&2
    exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
tar -xJf "$WORK/$ARCHIVE" -C "$DEST" --strip-components=1
GOT_VERSION="$("$DEST/bin/node" --version)" # fails here where the host cannot run it
echo "Node.js $GOT_VERSION is in .tools/node"
