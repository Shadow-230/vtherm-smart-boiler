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
    reason="vendor/ is not set up (docs/en/development/plans/plan-0.1.md, A5)",
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
        "compose.vendored.yaml",
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
    (root / "devenv/compose.vendored.yaml").symlink_to(ROOT / "devenv/compose.vendored.yaml")
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
    [["--instance", "9"], ["--instance", "0"], ["--instance"], ["--instance", "2x"]],
)
def test_an_unknown_instance_is_refused(tmp_path: Path, arguments: list[str]) -> None:
    """Test instances 1 to 8 exist: anything else is refused before anything is read."""
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
        (
            "8",
            "TEST_HA_DIR_8=/srv/test-ha-8\nTEST_HA_DIR_6=/srv/test-ha-8\n",
            "TEST_HA_DIR_8 must not be TEST_HA_DIR_6",
        ),
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
        "eighth_same_as_sixth",
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
    """The first instance stays ha-test on 8123; instance N = 2-8 is ha-test-N on 8122 + N. The
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
    reason="vendor/ is not set up (docs/en/development/plans/plan-0.1.md, A5)",
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
    for name in ("relay", "entity", "standalone"):
        text = (ROOT / f"devenv/config/{name}.yaml").read_text(encoding="utf-8")
        assert "\nj4_faults:\n" in text, name


# --- Versions only on the user's word (2026-11-17): --own-vt and --ha, the remote part run here --


def _deploy_root(tmp_path: Path, *, vendor: bool = True) -> tuple[Path, Path, Path]:
    """A copy of the deploy's root — the script, devenv/ (compose files, the configuration, a
    local.env naming an instance directory here, a dummy key), the plugin, the simulator's
    integrations and, with ``vendor``, stub vendored VT and SmartPI — and fake ``ssh`` and
    ``docker``: ssh runs the remote part here with the stream on its input, docker writes what
    it was asked into a log. Nothing connects anywhere. Returns the script, the instance's
    directory and the docker log."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts/deploy_test.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "devenv/config").mkdir(parents=True)
    for name in ("compose.yaml", "compose.vendored.yaml"):
        (root / "devenv" / name).write_text(
            (ROOT / "devenv" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (root / "devenv/config/configuration.yaml").write_text("{}\n", encoding="utf-8")
    components = [root / "custom_components/vtherm_smart_boiler"] + [
        root / "sim/custom_components" / name
        for name in ("boiler_sim", "opentherm_gw", "j4_faults")
    ]
    if vendor:
        components += [
            root / "vendor/custom_components" / name
            for name in ("versatile_thermostat", "vtherm_smartpi")
        ]
    for component in components:
        component.mkdir(parents=True)
        (component / "manifest.json").write_text('{"version": "vendored"}', encoding="utf-8")
    instance = tmp_path / "instance"
    instance.mkdir()
    (instance / ".vtherm-smart-boiler-test-ha").write_text("", encoding="utf-8")
    (root / "devenv/local.env").write_text(
        f"TEST_HA_HOST=host.invalid\nTEST_HA_SSH_USER=nobody\nTEST_HA_DIR='{instance}'\n",
        encoding="utf-8",
    )
    (root / "devenv/ssh").mkdir()
    (root / "devenv/ssh/id_ed25519").write_text("not a key\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ssh").write_text('#!/bin/sh\nfor last; do :; done\nexec sh -c "$last"\n')
    log = tmp_path / "docker.log"
    (bin_dir / "docker").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    for tool in ("ssh", "docker"):
        (bin_dir / tool).chmod(0o755)
    return script, instance, log


def _run(script: Path, tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(script), *arguments],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _env(instance: Path) -> dict[str, str]:
    lines = (instance / ".env").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines)


OLD_COMPOSE = (
    "services:\n  homeassistant:\n"
    "    image: ghcr.io/home-assistant/home-assistant:2026.9.3"
    "  # the version the plugin is built on\n"
)


def test_a_deploy_keeps_the_home_assistant_version_the_instance_runs(tmp_path: Path) -> None:
    """Versions change only on the user's word: without --ha, an instance deployed before keeps
    the image its compose.yaml named, then the one its .env keeps; VT and SmartPI as vendored,
    their compose file in COMPOSE_FILE."""
    script, instance, log = _deploy_root(tmp_path)
    (instance / "compose.yaml").write_text(OLD_COMPOSE, encoding="utf-8")
    result = _run(script, tmp_path)
    assert result.returncode == 0, result.stderr
    env = _env(instance)
    assert env["HA_VERSION"] == "2026.9.3"
    assert env["COMPOSE_FILE"] == "compose.yaml:compose.vendored.yaml"
    assert (instance / "custom_components/versatile_thermostat/manifest.json").is_file()
    assert "${HA_VERSION:?" in (instance / "compose.yaml").read_text(encoding="utf-8")
    assert log.read_text(encoding="utf-8").splitlines() == [
        "compose up -d",
        "compose restart homeassistant",
    ]
    again = _run(script, tmp_path)
    assert again.returncode == 0, again.stderr
    assert _env(instance)["HA_VERSION"] == "2026.9.3"  # from its .env now


def test_ha_sets_the_version_on_the_users_word(tmp_path: Path) -> None:
    script, instance, _log = _deploy_root(tmp_path)
    (instance / "compose.yaml").write_text(OLD_COMPOSE, encoding="utf-8")
    result = _run(script, tmp_path, "--ha", "2026.11.1")
    assert result.returncode == 0, result.stderr
    assert _env(instance)["HA_VERSION"] == "2026.11.1"
    kept = _run(script, tmp_path)
    assert kept.returncode == 0, kept.stderr
    assert _env(instance)["HA_VERSION"] == "2026.11.1"


def test_an_unknown_version_stops_the_deploy_before_anything_changes(tmp_path: Path) -> None:
    """A new instance without --ha: neither a .env nor a compose.yaml to keep a version from —
    the deploy stops, nothing unpacked, written or started."""
    script, instance, log = _deploy_root(tmp_path)
    result = _run(script, tmp_path)
    assert result.returncode == 4
    assert "--ha VERSION" in result.stderr
    assert sorted(path.name for path in instance.iterdir()) == [".vtherm-smart-boiler-test-ha"]
    assert not log.exists()


def test_own_vt_sends_neither_vt_nor_smartpi_and_mounts_the_instances_own(
    tmp_path: Path,
) -> None:
    """--own-vt (the user, 2026-11-17): VT and SmartPI are neither sent nor mounted — vendor/
    is not even needed — and COMPOSE_FILE leaves compose.vendored.yaml out, so the instance runs
    those installed in its own config/custom_components; the plugin and the simulator go as
    always."""
    script, instance, log = _deploy_root(tmp_path, vendor=False)
    (instance / "compose.yaml").write_text(OLD_COMPOSE, encoding="utf-8")
    for name in ("versatile_thermostat", "vtherm_smartpi"):
        own = instance / "config/custom_components" / name
        own.mkdir(parents=True)
        (own / "manifest.json").write_text('{"version": "own"}', encoding="utf-8")
    dry = _run(script, tmp_path, "--dry-run", "--own-vt")
    assert dry.returncode == 0, dry.stderr
    assert "versatile_thermostat" not in dry.stdout
    assert "vtherm_smartpi" not in dry.stdout
    assert "the instance's own" in dry.stdout
    result = _run(script, tmp_path, "--own-vt")
    assert result.returncode == 0, result.stderr
    assert _env(instance)["COMPOSE_FILE"] == "compose.yaml"
    assert not (instance / "custom_components/versatile_thermostat").exists()
    assert (instance / "custom_components/vtherm_smart_boiler/manifest.json").is_file()
    for name in ("versatile_thermostat", "vtherm_smartpi"):
        manifest = instance / "config/custom_components" / name / "manifest.json"
        assert manifest.read_text(encoding="utf-8") == '{"version": "own"}'
    assert "compose up -d" in log.read_text(encoding="utf-8")


def test_own_vt_without_vt_in_the_instance_stops_before_anything_changes(tmp_path: Path) -> None:
    script, instance, log = _deploy_root(tmp_path, vendor=False)
    (instance / "compose.yaml").write_text(OLD_COMPOSE, encoding="utf-8")
    result = _run(script, tmp_path, "--own-vt")
    assert result.returncode == 5
    assert "versatile_thermostat of its own" in result.stderr
    assert (instance / "compose.yaml").read_text(encoding="utf-8") == OLD_COMPOSE
    assert not (instance / ".env").exists()
    assert not (instance / ".incoming").exists()
    assert not log.exists()


@pytest.mark.parametrize(
    "arguments", [["--ha"], ["--ha", "--own-vt"], ["--ha", "2026.11;rm"], ["--ha", "a b"]]
)
def test_a_bad_home_assistant_version_is_refused(tmp_path: Path, arguments: list[str]) -> None:
    script, _instance, log = _deploy_root(tmp_path)
    result = _run(script, tmp_path, *arguments)
    assert result.returncode == 2
    assert "usage" in result.stderr
    assert not log.exists()
