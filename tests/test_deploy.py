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
    ):
        assert expected in names, expected
    assert not [line for line in entries if line.startswith("l")], "links in the archive"
    assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]
    assert not [name for name in names if name.startswith(("sim/", "vendor/", "plugin/"))]


def test_an_unknown_argument_is_refused() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--now"], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 2
    assert "usage" in result.stderr


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
