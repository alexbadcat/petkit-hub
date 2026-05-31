"""PetKit Pura Max / Pura Max 2 (device_type ``t4``) plugin.

Maps the cloud ``Litter`` model to Home Assistant entities and wires control
buttons/switches/selects through the pypetkitapi command API.
See ``DEV_NOTES.md`` for the reverse-engineered field & command reference.
"""
from __future__ import annotations

from typing import Any

from pypetkitapi.command import (
    DeviceAction,
    DeviceCommand,
    LBCommand,
    LitterCommand,
)

from ...plugins_base import Entity, PetkitPlugin


# --- small accessors ----------------------------------------------------------
def _st(device: Any, attr: str, default: Any = None) -> Any:
    return getattr(getattr(device, "state", None), attr, default)


def _cfg(device: Any, attr: str, default: Any = None) -> Any:
    return getattr(getattr(device, "settings", None), attr, default)


def _stats(device: Any, attr: str, default: Any = None) -> Any:
    return getattr(getattr(device, "device_stats", None), attr, default)


# --- command factories --------------------------------------------------------
def _action(action: DeviceAction, lb: LBCommand):
    async def _run(client, device, _payload):
        await client.send_api_request(device.id, DeviceCommand.CONTROL_DEVICE, {action: lb})
    return _run


def _reset_n50():
    async def _run(client, device, _payload):
        await client.send_api_request(device.id, LitterCommand.RESET_N50_DEODORIZER)
    return _run


def _switch(api_key: str):
    async def _run(client, device, payload):
        await client.send_api_request(
            device.id, DeviceCommand.UPDATE_SETTING, {api_key: 1 if payload == "ON" else 0}
        )
    return _run


def _select(api_key: str, options: dict[str, int]):
    async def _run(client, device, payload):
        if payload in options:
            await client.send_api_request(
                device.id, DeviceCommand.UPDATE_SETTING, {api_key: options[payload]}
            )
    return _run


SAND_TYPES = {"Bentonite": 1, "Tofu": 2, "Mixed": 3}
SAND_TYPES_REV = {v: k for k, v in SAND_TYPES.items()}


class PuraMaxPlugin(PetkitPlugin):
    slug = "puramax"
    name = "PetKit Pura Max / Max 2"
    handles = {"t4"}

    def entities(self, device: Any) -> list[Entity]:
        return [
            # --- sensors ------------------------------------------------------
            Entity("litter_percent", "Litter level", "sensor", unit="%",
                   icon="mdi:gauge", value=lambda d: _st(d, "sand_percent")),
            Entity("litter_weight", "Litter weight", "sensor", unit="g", device_class="weight",
                   icon="mdi:weight-gram", value=lambda d: _st(d, "sand_weight")),
            Entity("used_times", "Uses", "sensor", icon="mdi:counter",
                   value=lambda d: _st(d, "used_times")),
            Entity("times_today", "Uses today", "sensor", icon="mdi:counter",
                   value=lambda d: _stats(d, "times")),
            Entity("avg_time", "Avg visit", "sensor", unit="s", device_class="duration",
                   icon="mdi:timer-outline", value=lambda d: _stats(d, "avg_time")),
            Entity("battery", "Battery", "sensor", unit="%", device_class="battery",
                   category="diagnostic", value=lambda d: _st(d, "battery")),
            Entity("liquid", "Pura Air liquid", "sensor", unit="%", icon="mdi:spray",
                   value=lambda d: _st(d, "liquid")),
            Entity("deodorant_left_days", "N50 days left", "sensor", unit="d",
                   icon="mdi:calendar-clock", value=lambda d: _st(d, "deodorant_left_days")),
            Entity("spray_left_days", "Spray days left", "sensor", unit="d",
                   icon="mdi:calendar-clock", category="diagnostic",
                   value=lambda d: _st(d, "spray_left_days")),
            Entity("error", "Error", "sensor", category="diagnostic", icon="mdi:alert-circle",
                   value=lambda d: _st(d, "error_msg") or _st(d, "error_code") or "OK"),
            Entity("sand_type_state", "Litter type", "sensor", icon="mdi:dots-grid",
                   category="diagnostic",
                   value=lambda d: SAND_TYPES_REV.get(_st(d, "sand_type"), "—")),

            # --- binary sensors ----------------------------------------------
            Entity("box_full", "Waste bin full", "binary_sensor", device_class="problem",
                   value=lambda d: bool(_st(d, "box_full"))),
            Entity("liquid_lack", "Liquid low", "binary_sensor", device_class="problem",
                   value=lambda d: bool(_st(d, "liquid_lack"))),
            Entity("sand_lack", "Litter low", "binary_sensor", device_class="problem",
                   value=lambda d: bool(_st(d, "sand_lack"))),
            Entity("low_power", "Low power", "binary_sensor", device_class="battery",
                   category="diagnostic", value=lambda d: bool(_st(d, "low_power"))),

            # --- buttons (actions) -------------------------------------------
            Entity("clean", "Clean now", "button", icon="mdi:broom",
                   command=_action(DeviceAction.START, LBCommand.CLEANING)),
            Entity("odor", "Deodorize", "button", icon="mdi:scent",
                   command=_action(DeviceAction.START, LBCommand.ODOR_REMOVAL)),
            Entity("dump", "Dump litter", "button", icon="mdi:delete-empty",
                   command=_action(DeviceAction.START, LBCommand.DUMPING)),
            Entity("maintenance_start", "Maintenance start", "button", icon="mdi:wrench",
                   command=_action(DeviceAction.START, LBCommand.MAINTENANCE)),
            Entity("maintenance_stop", "Maintenance stop", "button", icon="mdi:wrench-outline",
                   command=_action(DeviceAction.END, LBCommand.MAINTENANCE)),
            Entity("light", "Light", "button", icon="mdi:lightbulb",
                   command=_action(DeviceAction.START, LBCommand.LIGHT)),
            Entity("reset_n50", "Reset N50", "button", category="config", icon="mdi:restart",
                   command=_reset_n50()),

            # --- switches (settings) -----------------------------------------
            Entity("auto_work", "Auto cleaning", "switch", category="config",
                   value=lambda d: bool(_cfg(d, "auto_work")), command=_switch("autoWork")),
            Entity("avoid_repeat", "Avoid repeat cleaning", "switch", category="config",
                   value=lambda d: bool(_cfg(d, "avoid_repeat")), command=_switch("avoidRepeat")),
            Entity("deep_clean", "Deep cleaning", "switch", category="config",
                   value=lambda d: bool(_cfg(d, "deep_clean")), command=_switch("deepClean")),
            Entity("bury", "Waste covering", "switch", category="config",
                   value=lambda d: bool(_cfg(d, "bury")), command=_switch("bury")),
            Entity("kitten", "Kitten mode", "switch", category="config",
                   value=lambda d: bool(_cfg(d, "kitten")), command=_switch("kitten")),
            Entity("disturb_mode", "Do not disturb", "switch", category="config",
                   value=lambda d: bool(_cfg(d, "disturb_mode")), command=_switch("disturbMode")),
            Entity("manual_lock", "Child lock", "switch", category="config",
                   value=lambda d: bool(_cfg(d, "manual_lock")), command=_switch("manualLock")),
            Entity("auto_spray", "Auto spray", "switch", category="config",
                   value=lambda d: bool(_cfg(d, "auto_spray")), command=_switch("autoSpray")),

            # --- select -------------------------------------------------------
            Entity("sand_type", "Litter type", "select", category="config",
                   options=list(SAND_TYPES), icon="mdi:dots-grid",
                   value=lambda d: SAND_TYPES_REV.get(_cfg(d, "sand_type"), "Bentonite"),
                   command=_select("sandType", SAND_TYPES)),
        ]


PLUGIN = PuraMaxPlugin()
