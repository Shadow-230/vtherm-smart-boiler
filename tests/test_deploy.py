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
        "custom_components/j4_faults/manifest.json",
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
    for name in ("boiler_sim", "opentherm_gw", "j4_faults"):
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
    assert "boiler_sim opentherm_gw j4_faults)" in script
    assert "custom_components/boiler_sim custom_components/opentherm_gw" in script
    assert "./custom_components/j4_faults:/config/custom_components/j4_faults:ro" in compose


def _copy_root(tmp_path: Path, test_ha_dir: str, extra: str = "") -> Path:
    """A copy of the script's root with stub vendor/ folders, a local.env naming an unreachable
    host and the given directory (``extra``: more lines of it), and no SSH key — so a run that
    got past the directory check would still stop at the missing key before any connection."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts/deploy_test.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    for name in ("versatile_thermostat", "vtherm_smartpi"):
        (root / "vendor/custom_components" / name).mkdir(parents=True)
    (root / "devenv/config").mkdir(parents=True)
    (root / "devenv/config/configuration.yaml").write_text("{}\n", encoding="utf-8")
    (root / "devenv/local.env").write_text(
        f"TEST_HA_HOST=host.invalid\nTEST_HA_SSH_USER=nobody\nTEST_HA_DIR='{test_ha_dir}'\n"
        + extra,
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
    for change in ("rm -rf", "tar -x", "mv ", "> .env", "docker compose"):
        assert remote.index(change) > marker, change
    assert "mkdir -p '$TEST_HA_DIR'" not in script


@pytest.mark.parametrize(
    "arguments",
    [["--instance", "6"], ["--instance", "0"], ["--instance"], ["--instance", "2x"]],
)
def test_an_unknown_instance_is_refused(tmp_path: Path, arguments: list[str]) -> None:
    """Test instances 1 to 5 exist: anything else is refused before anything is read."""
    script = _copy_root(tmp_path, "/srv/test-ha")
    result = subprocess.run(
        ["bash", str(script), *arguments], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 2
    assert "usage" in result.stderr


@pytest.mark.parametrize(
    ("instance", "extra", "message"),
    [
        ("2", "", "TEST_HA_DIR_2 is empty"),
        ("4", "TEST_HA_DIR_2=/srv/test-ha-2\n", "TEST_HA_DIR_4 is empty"),
        ("2", "TEST_HA_DIR_2=/srv/test-ha\n", "TEST_HA_DIR_2 must not be TEST_HA_DIR"),
        ("2", "TEST_HA_DIR_2=/srv/test-ha/\n", "TEST_HA_DIR_2 must not be TEST_HA_DIR"),
        (
            "3",
            "TEST_HA_DIR_2=/srv/test-ha-2\nTEST_HA_DIR_3=/srv/test-ha-2\n",
            "TEST_HA_DIR_3 must not be TEST_HA_DIR_2",
        ),
        ("1", "TEST_HA_DIR_4=/srv/test-ha\n", "TEST_HA_DIR must not be TEST_HA_DIR_4"),
        ("5", "TEST_HA_DIR_5=/srv/test-ha/\n", "TEST_HA_DIR_5 must not be TEST_HA_DIR"),
        ("2", "TEST_HA_DIR_2=/srv/..\n", "TEST_HA_DIR must be"),
        ("3", "TEST_HA_DIR_3=/srv/test-ha-3\n", "id_ed25519 is missing"),
    ],
    ids=[
        "missing",
        "missing_4",
        "same_as_first",
        "same_with_slash",
        "same_as_second",
        "first_same_as_fourth",
        "fifth_same_as_first",
        "looks_deeper",
        "plain",
    ],
)
def test_each_instance_has_a_directory_of_its_own(
    tmp_path: Path, instance: str, extra: str, message: str
) -> None:
    """No instance deploys into another one's directory, and each directory passes the same
    check; a plain one goes on and stops at the missing key, so nothing connects."""
    script = _copy_root(tmp_path, "/srv/test-ha", extra)
    result = subprocess.run(
        ["bash", str(script), "--instance", instance],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert message in result.stderr


def test_each_instance_gets_its_own_container_and_port() -> None:
    """The first instance stays ha-test on 8123; instance N = 2-5 is ha-test-N on 8122 + N. The
    script writes them into the .env beside compose.yaml, which compose reads for the name and
    the published port."""
    compose = (ROOT / "devenv/compose.yaml").read_text(encoding="utf-8")
    assert "container_name: ${HA_CONTAINER:-ha-test}" in compose
    assert '"${HA_PORT:-8123}:8123"' in compose
    script = SCRIPT.read_text(encoding="utf-8")
    assert "    CONTAINER=ha-test\n    DIR_VAR=TEST_HA_DIR\n" in script
    assert '    CONTAINER="ha-test-$INSTANCE"\n    DIR_VAR="TEST_HA_DIR_$INSTANCE"\n' in script
    assert "PORT=$((8122 + INSTANCE))" in script
    assert "HA_CONTAINER=%s" in script
    assert "HA_PORT=%s" in script


@pytest.mark.skipif(
    not (ROOT / "vendor/custom_components/versatile_thermostat").is_dir(),
    reason="vendor/ is not set up (docs/plan-0.1.md, A5)",
)
def test_a_chosen_configuration_goes_as_configuration_yaml(tmp_path: Path) -> None:
    """``--config starts`` sends devenv/config/starts.yaml as the instance's configuration.yaml
    — the size listed is that file's — and nothing else under config/; the dry run connects
    nowhere."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "connected"
    for tool in ("ssh", "scp", "rsync", "sftp"):
        fake = bin_dir / tool
        fake.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 97\n')
        fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--instance", "2", "--config", "starts"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    configs = [line.split() for line in result.stdout.splitlines()[1:] if " config/" in line]
    assert [fields[-1] for fields in configs] == ["config/configuration.yaml"]
    assert int(configs[0][2]) == (ROOT / "devenv/config/starts.yaml").stat().st_size


@pytest.mark.parametrize(
    ("name", "code", "message"),
    [
        ("../configuration", 2, "usage"),
        ("Starts", 2, "usage"),
        ("", 2, "usage"),
        ("missing", 1, "devenv/config/missing.yaml does not exist"),
    ],
)
def test_an_unknown_configuration_is_refused(
    tmp_path: Path, name: str, code: int, message: str
) -> None:
    """Only a plain name of a file in devenv/config/ is taken."""
    script = _copy_root(tmp_path, "/srv/test-ha")
    result = subprocess.run(
        ["bash", str(script), "--dry-run", "--config", name],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == code
    assert message in result.stderr


def test_the_starts_configuration_is_the_in_process_comparisons_house() -> None:
    """J4's starts criterion in the test HA runs the house of tests/sim/test_control_loop.py's
    comparison: the large condensing boiler on its own regulation without a wall thermostat,
    three radiator zones on switch valves, and a ±3 K daily swing around a mean set per run."""
    text = (ROOT / "devenv/config/starts.yaml").read_text(encoding="utf-8")
    for expected in (
        "boiler: condensing_large",
        "zones: radiators",
        "valves: switch",
        "topology: with_thermostat",
        "action: boiler_sim.set_outdoor",
        "input_number.j4_outdoor_mean",
        "+ 3 * cos(2 * pi * (hour - 15) / 24)",
    ):
        assert expected in text, expected
    assert "wall_thermostat" not in text.split("boiler_sim:")[1].split("input_number:")[0]


def test_the_fault_injector_is_never_part_of_the_release() -> None:
    """J4's fault injector reaches into the plugin: it lives with the simulator, outside the
    plugin's folder — the only one a release ships — and the test configuration names it."""
    assert (ROOT / "sim/custom_components/j4_faults/manifest.json").is_file()
    assert not (ROOT / "custom_components/j4_faults").exists()
    plugin = (ROOT / "custom_components/vtherm_smart_boiler").rglob("*.py")
    assert not [p for p in plugin if "j4_faults" in p.read_text(encoding="utf-8")]
    assert "\nj4_faults:\n" in (ROOT / "devenv/config/configuration.yaml").read_text(
        encoding="utf-8"
    )
    assert "j4_faults" not in (ROOT / "devenv/config/starts.yaml").read_text(encoding="utf-8")
