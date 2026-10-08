"""A small async client for one test Home Assistant instance, for J4 (docs/plan-0.2.md).

Everything about where it goes comes from devenv/local.env (git-ignored): the instance is
HA_INSTANCE (1 to 5, default 1), its URL TEST_HA_URL[_N] — refused unless it is TEST_HA_HOST on
port 8122 + N — and its token TEST_HA_TOKEN[_N], or TEST_HA_TOKEN where the instances share the
first one's login (devenv/README.md, section 6). It connects to nothing else.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import time
from urllib.parse import urlsplit

import aiohttp

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV = ROOT / "devenv/local.env"
CFG = dict(
    line.split("=", 1)
    for line in ENV.read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
N = os.environ.get("HA_INSTANCE", "1")
SFX = "" if N == "1" else "_" + N
URL = CFG["TEST_HA_URL" + SFX].rstrip("/")
TOKEN = CFG.get("TEST_HA_TOKEN" + SFX) or CFG["TEST_HA_TOKEN"]
_parts = urlsplit(URL)
if (_parts.scheme, _parts.hostname, _parts.port) != ("http", CFG["TEST_HA_HOST"], 8122 + int(N)):
    raise SystemExit(f"{URL} is not test instance {N} on TEST_HA_HOST: refused")
CONTAINER = "ha-test" if N == "1" else f"ha-test-{N}"
SIGNALS = (
    "flame",
    "flow",
    "return",
    "modulation",
    "ch_setpoint",
    "dhw_active",
    "pressure",
    "outdoor",
    "ch_active",
    "pump_running",
    "weather",
    "gateway",
    "gateway_all",
    "thermostat_setpoint",
)
KINDS = {
    "set_control_setpoint": ("setpoint", "temperature"),
    "set_central_heating_ovrd": ("ch", "ch_override"),
    "set_hot_water_ovrd": ("hot_water", "dhw_override"),
    "set_max_modulation": ("max_modulation", "level"),
}


class HA:
    def __init__(self) -> None:
        self.gw: list[tuple[float, str, object]] = []  # (time, kind, value) of opentherm_gw calls
        self.calls: list[tuple[float, str, str, dict]] = []
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}

    async def __aenter__(self) -> HA:
        self.session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {TOKEN}"})
        await self._connect()
        return self

    async def __aexit__(self, *exc) -> None:
        self._reader.cancel()
        await self.ws.close()
        await self.session.close()

    async def _connect(self) -> None:
        self.ws = await self.session.ws_connect(
            URL.replace("http", "ws") + "/api/websocket", heartbeat=30
        )
        await self.ws.receive_json()
        await self.ws.send_json({"type": "auth", "access_token": TOKEN})
        assert (await self.ws.receive_json())["type"] == "auth_ok"
        self._reader = asyncio.create_task(self._read())
        await self.ws_cmd({"type": "subscribe_events", "event_type": "call_service"})

    async def _read(self) -> None:
        async for msg in self.ws:
            data = json.loads(msg.data)
            if data.get("type") == "event":
                ev = data["event"]["data"]
                t = time.time()
                self.calls.append(
                    (t, ev.get("domain"), ev.get("service"), ev.get("service_data") or {})
                )
                if ev.get("domain") == "opentherm_gw" and ev.get("service") in KINDS:
                    kind, key = KINDS[ev["service"]]
                    self.gw.append((t, kind, (ev.get("service_data") or {}).get(key)))
            elif data.get("id") in self._pending:
                self._pending.pop(data["id"]).set_result(data)

    async def ws_cmd(self, payload: dict) -> dict:
        self._id += 1
        payload = {**payload, "id": self._id}
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._id] = fut
        await self.ws.send_json(payload)
        res = await asyncio.wait_for(fut, 60)
        if not res.get("success", True):
            raise RuntimeError(f"{payload['type']}: {res.get('error')}")
        return res.get("result")

    async def rest(self, method: str, path: str, body: dict | None = None):
        async with self.session.request(method, URL + path, json=body) as r:
            text = await r.text()
            try:
                return r.status, json.loads(text)
            except ValueError:
                return r.status, text

    async def call(self, domain: str, service: str, **data) -> dict | None:
        """A service call over the WebSocket; an error comes back as {'error': ...}."""
        try:
            return await self.ws_cmd(
                {"type": "call_service", "domain": domain, "service": service, "service_data": data}
            )
        except RuntimeError as err:
            return {"error": str(err)}

    async def states(self) -> dict[str, dict]:
        _s, st = await self.rest("GET", "/api/states")
        return {s["entity_id"]: s for s in st}

    async def state(self, entity_id: str) -> dict | None:
        s, st = await self.rest("GET", f"/api/states/{entity_id}")
        return st if s == 200 else None

    async def entities(self) -> dict[str, str]:
        """translation_key -> entity_id for the plugin's entities (the registry)."""
        reg = await self.ws_cmd({"type": "config/entity_registry/list"})
        return {
            e["translation_key"]: e["entity_id"]
            for e in reg
            if e.get("platform") == "vtherm_smart_boiler" and e.get("translation_key")
        }

    async def issues(self) -> list[dict]:
        res = await self.ws_cmd({"type": "repairs/list_issues"})
        return [
            i
            for i in res["issues"]
            if i.get("domain") == "vtherm_smart_boiler" and not i.get("dismissed_version")
        ]

    async def entry(self, domain: str, title: str | None = None) -> dict:
        _s, entries = await self.rest("GET", "/api/config/config_entries/entry")
        return next(
            e for e in entries if e["domain"] == domain and (title is None or e["title"] == title)
        )

    async def wait(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def until(self, predicate, within: float, poll: float = 2.0) -> float | None:
        """Seconds until ``await predicate()`` holds, or None after ``within`` seconds."""
        start = time.time()
        while time.time() - start < within:
            if await predicate():
                return time.time() - start
            await asyncio.sleep(poll)
        return None

    def since(self, t: float, kind: str | None = None) -> list[tuple[float, str, object]]:
        return [c for c in self.gw if c[0] >= t and (kind is None or c[1] == kind)]


def ssh(command: str, timeout: int = 120) -> str:
    """A command in the test LXC as the deploy user (devenv/local.env's host only)."""
    root = ROOT
    args = [
        "ssh",
        "-F",
        "/dev/null",
        "-i",
        f"{root}/devenv/ssh/id_ed25519",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        f"UserKnownHostsFile={root}/devenv/ssh/known_hosts",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "StrictHostKeyChecking=yes",
        f"{CFG['TEST_HA_SSH_USER']}@{CFG['TEST_HA_HOST']}",
        command,
    ]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
