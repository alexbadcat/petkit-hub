"""MQTT topic + Home Assistant discovery payload helpers.

The runtime owns the aiomqtt client lifecycle; this module is pure topic/payload
construction so it is trivially unit-testable (see ``--selftest``).
"""
from __future__ import annotations

from typing import Any

from .plugins_base import Entity

DISCOVERY_PREFIX = "homeassistant"
BASE = "petkit_hub"


# --- topics -------------------------------------------------------------------
def state_topic(device_id: Any) -> str:
    return f"{BASE}/{device_id}/state"


def availability_topic(device_id: Any) -> str:
    return f"{BASE}/{device_id}/availability"


def command_topic(device_id: Any, key: str) -> str:
    return f"{BASE}/{device_id}/cmd/{key}"


def command_subscription() -> str:
    return f"{BASE}/+/cmd/#"


def parse_command_topic(topic: str) -> tuple[str, str] | None:
    """``petkit_hub/<device_id>/cmd/<key>`` -> (device_id, key)."""
    parts = topic.split("/")
    if len(parts) >= 4 and parts[0] == BASE and parts[2] == "cmd":
        return parts[1], "/".join(parts[3:])
    return None


# --- discovery ----------------------------------------------------------------
_CONTROLLABLE = {"button", "switch", "select", "number", "text"}


def discovery_payload(device_id: Any, device_meta: dict, ent: Entity) -> tuple[str, dict]:
    """Build the ``homeassistant/<component>/<node>/<key>/config`` topic + payload."""
    node = f"petkit_{device_id}"
    uid = f"{node}_{ent.key}"
    topic = f"{DISCOVERY_PREFIX}/{ent.component}/{node}/{ent.key}/config"

    payload: dict[str, Any] = {
        "name": ent.name,
        "unique_id": uid,
        "object_id": uid,
        "availability_topic": availability_topic(device_id),
        "device": device_meta,
    }
    if ent.icon:
        payload["icon"] = ent.icon
    if ent.device_class:
        payload["device_class"] = ent.device_class
    if ent.unit:
        payload["unit_of_measurement"] = ent.unit
    if ent.category:
        payload["entity_category"] = ent.category

    # stateful entities read from the shared JSON state topic
    if ent.value is not None or ent.component in ("sensor", "binary_sensor", "switch", "select", "number", "text"):
        payload["state_topic"] = state_topic(device_id)
        payload["value_template"] = "{{ value_json.%s }}" % ent.key

    # controllable entities get a command topic
    if ent.component in _CONTROLLABLE:
        payload["command_topic"] = command_topic(device_id, ent.key)

    if ent.component == "button":
        payload["payload_press"] = "PRESS"
        payload.pop("state_topic", None)
        payload.pop("value_template", None)
    elif ent.component == "switch":
        payload.setdefault("payload_on", "ON")
        payload.setdefault("payload_off", "OFF")
        payload.setdefault("state_on", "ON")
        payload.setdefault("state_off", "OFF")
    elif ent.component == "select":
        payload["options"] = ent.options or []
    elif ent.component == "binary_sensor":
        payload.setdefault("payload_on", "ON")
        payload.setdefault("payload_off", "OFF")

    payload.update(ent.extra or {})
    return topic, payload


def _selftest() -> None:
    meta = {"identifiers": ["petkit_1"], "name": "Box", "manufacturer": "PetKit"}
    samples = [
        Entity("litter_percent", "Litter", "sensor", unit="%", value=lambda d: 80),
        Entity("clean", "Clean", "button", command=lambda *a: None),
        Entity("auto_work", "Auto", "switch", value=lambda d: "ON", command=lambda *a: None),
        Entity("sand_type", "Litter type", "select", options=["a", "b"], command=lambda *a: None),
    ]
    for e in samples:
        t, p = discovery_payload(1, meta, e)
        assert t.startswith(DISCOVERY_PREFIX) and p["unique_id"] == f"petkit_1_{e.key}"
    assert parse_command_topic("petkit_hub/1/cmd/clean") == ("1", "clean")
    print("mqtt selftest OK")


if __name__ == "__main__":
    _selftest()
