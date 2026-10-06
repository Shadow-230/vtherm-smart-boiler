"""The test deployment (P55): files, never links into vendor/, and a dry run that connects
nowhere."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy_test.sh"


@pytest.mark.skipif(
    not (ROOT / "vendor/custom_components/versatile_thermostat").is_dir(),
    reason="vendor/ is not set up (docs/plan-0.1.md, A5)",
)
def test_the_dry_run_lists_files_and_connects_nowhere(tmp_path: Path) -> None:
    # Anything that could reach the host fails loudly and leaves a mark.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "connected"
    for tool in ("ssh", "scp", "rsync", "sftp"):
        fake = bin_dir / tool
        fake.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 97\n')
        fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    entries = result.stdout.splitlines()[1:]  # after the "Would deploy to" line
    names = {line.split()[-1] for line in entries}
    for expected in (
        "compose.yaml",
        "config/configuration.yaml",
        "custom_components/vtherm_smart_boiler/manifest.json",
        "custom_components/versatile_thermostat/manifest.json",
        "custom_components/vtherm_smartpi/manifest.json",
        "custom_components/boiler_sim/manifest.json",
        "custom_components/boiler_sim/plant.py",
        "custom_components/opentherm_gw/manifest.json",
        "custom_components/opentherm_gw/translations/en.json",
    ):
        assert expected in names, expected
    assert not [line for line in entries if line.startswith("l")], "links in the archive"
    assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]
    assert not [name for name in names if name.startswith(("sim/", "vendor/", "plugin/"))]


def test_the_dry_run_reads_no_private_file(tmp_path: Path) -> None:
    """P-107: the dry run lists what would go, and reads nothing private — a
    ``devenv/local.env`` that fails when sourced does not stop it, and no host from it is
    printed. The script runs from a copy of its root, so the real file is never touched."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts/deploy_test.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "devenv/config").mkdir(parents=True)
    (root / "devenv/compose.yaml").symlink_to(ROOT / "devenv/compose.yaml")
    (root / "devenv/config/configuration.yaml").symlink_to(
        ROOT / "devenv/config/configuration.yaml"
    )
    (root / "devenv/local.env").write_text(
        "TEST_HA_HOST=leaked.example\necho POISONED >&2\nexit 42\n", encoding="utf-8"
    )
    (root / "custom_components").mkdir()
    (root / "custom_components/vtherm_smart_boiler").symlink_to(
        ROOT / "custom_components/vtherm_smart_boiler"
    )
    (root / "sim/custom_components").mkdir(parents=True)
    for name in ("boiler_sim", "opentherm_gw"):
        (root / "sim/custom_components" / name).symlink_to(ROOT / "sim/custom_components" / name)
    for name in ("versatile_thermostat", "vtherm_smartpi"):
        stub = root / "vendor/custom_components" / name
        stub.mkdir(parents=True)
        (stub / "manifest.json").write_text("{}", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "POISONED" not in result.stderr
    assert "leaked.example" not in result.stdout + result.stderr
    assert result.stdout.splitlines()[0] == (
        "Would deploy to the test HA named in devenv/local.env:"
    )


def test_an_unknown_argument_is_refused(tmp_path: Path) -> None:
    """PB-90: run from a copy of its root with stub vendor/ folders, no ``devenv/local.env``
    and no key, and with fake ssh, scp, rsync and sftp first in PATH that leave a mark — so a
    regression in the argument check could never reach the test HA from a plain test run."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts/deploy_test.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    for name in ("versatile_thermostat", "vtherm_smartpi"):
        (root / "vendor/custom_components" / name).mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "connected"
    for tool in ("ssh", "scp", "rsync", "sftp"):
        fake = bin_dir / tool
        fake.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 97\n')
        fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", str(script), "--now"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert "usage" in result.stderr
    assert not marker.exists()


def test_ssh_reads_no_configuration_but_its_own() -> None:
    """T7: ~/.ssh/config or /etc/ssh/ssh_config could send the deploy elsewhere (a Host alias, a
    ProxyJump) or reuse a connection; only devenv/local.env says where it goes."""
    script = SCRIPT.read_text(encoding="utf-8")
    for option in (
        "-F /dev/null",
        "IdentitiesOnly=yes",
        "BatchMode=yes",
        "ControlMaster=no",
        "ControlPath=none",
        "GlobalKnownHostsFile=/dev/null",
    ):
        assert option in script, option
    assert "unset TEST_HA_HOST" in script  # nothing from the calling environment


def test_the_stub_goes_only_where_compose_mounts_it() -> None:
    """P-37: the test-only gateway stub is packed and mounted for the test Home Assistant, as
    every other integration under test, and the script names it among those it replaces."""
    compose = (ROOT / "devenv/compose.yaml").read_text(encoding="utf-8")
    assert "./custom_components/opentherm_gw:/config/custom_components/opentherm_gw:ro" in compose
    script = SCRIPT.read_text(encoding="utf-8")
    assert "boiler_sim opentherm_gw)" in script
    assert "custom_components/boiler_sim custom_components/opentherm_gw" in script


def _copy_root(tmp_path: Path, test_ha_dir: str) -> Path:
    """A copy of the script's root with stub vendor/ folders, a local.env naming an unreachable
    host and the given directory, and no SSH key — so a run that got past the directory check
    would still stop at the missing key before any connection."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts/deploy_test.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    for name in ("versatile_thermostat", "vtherm_smartpi"):
        (root / "vendor/custom_components" / name).mkdir(parents=True)
    (root / "devenv").mkdir()
    (root / "devenv/local.env").write_text(
        f"TEST_HA_HOST=host.invalid\nTEST_HA_SSH_USER=nobody\nTEST_HA_DIR='{test_ha_dir}'\n",
        encoding="utf-8",
    )
    return script


@pytest.mark.parametrize(
    "test_ha_dir",
    ["/opt/", "/opt/..", "/opt/./", "//etc", "/opt/./ha", "/srv/ha/", "/opt/../etc", "/opt/h a"],
)
def test_a_directory_that_only_looks_deeper_is_refused(tmp_path: Path, test_ha_dir: str) -> None:
    """PB-87: "/opt/.." is "/", "//etc" is "/etc"; such a TEST_HA_DIR, a trailing slash and an
    unusual character are refused before anything else happens."""
    script = _copy_root(tmp_path, test_ha_dir)
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 1
    assert "TEST_HA_DIR must be" in result.stderr


def test_a_plain_directory_passes_the_check(tmp_path: Path) -> None:
    """The check refuses only what it should: a plain path goes on, and stops at the missing
    key (the copy has none), so nothing connects."""
    script = _copy_root(tmp_path, "/srv/test-ha")
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 1
    assert "id_ed25519 is missing" in result.stderr


def test_the_host_must_show_the_test_marker_before_anything_changes() -> None:
    """PB-87: on the host, the marker the user creates at J2 is checked before anything is
    unpacked, replaced or restarted, and a missing directory is not created."""
    script = SCRIPT.read_text(encoding="utf-8")
    remote = script[script.index('pack | "${SSH[@]}"') :]
    marker = remote.index("if [ ! -f '$MARKER' ]")
    assert "MARKER=.vtherm-smart-boiler-test-ha" in script
    for change in ("rm -rf", "tar -x", "mv ", "docker compose"):
        assert remote.index(change) > marker, change
    assert "mkdir -p '$TEST_HA_DIR'" not in script
