"""Talk to the HA Supervisor: fetch MQTT broker credentials automatically.

When the add-on declares ``services: [mqtt:need]`` and the Mosquitto add-on (or any
MQTT service) is configured, the Supervisor exposes the broker config here, so the
user never types broker host/user/pass.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger("petkit_hub.supervisor")

SUPERVISOR = "http://supervisor"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")


@dataclass
class MqttConfig:
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    ssl: bool = False


def _headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


async def mqtt_config() -> MqttConfig | None:
    """Return broker config from the Supervisor, or None if unavailable.

    Honours env overrides (MQTT_HOST/PORT/USERNAME/PASSWORD) for local dev.
    """
    if os.environ.get("MQTT_HOST"):
        return MqttConfig(
            host=os.environ["MQTT_HOST"],
            port=int(os.environ.get("MQTT_PORT", "1883")),
            username=os.environ.get("MQTT_USERNAME") or None,
            password=os.environ.get("MQTT_PASSWORD") or None,
            ssl=os.environ.get("MQTT_SSL", "").lower() in ("1", "true", "yes"),
        )
    if not TOKEN:
        log.warning("no SUPERVISOR_TOKEN and no MQTT_HOST override — MQTT disabled")
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{SUPERVISOR}/services/mqtt", headers=_headers())
            r.raise_for_status()
            d = r.json()["data"]
        return MqttConfig(
            host=d["host"], port=int(d["port"]),
            username=d.get("username") or None, password=d.get("password") or None,
            ssl=bool(d.get("ssl", False)),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not fetch MQTT config from supervisor: %s", exc)
        return None
