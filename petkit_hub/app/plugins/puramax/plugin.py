"""PetKit Pura Max / Pura Max 2 (device_type ``t4``) plugin.

Entity keys are kept identical to the RobertD502 ha-petkit integration so the
existing «Туалет Рижика» card + the `litter.yaml` health package work unchanged
(drop-in replacement). See DEV_NOTES.md for the field/command reference.
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


# --- accessors ----------------------------------------------------------------
def _st(d, a, default=None):
    return getattr(getattr(d, "state", None), a, default)


def _cfg(d, a, default=None):
    return getattr(getattr(d, "settings", None), a, default)


def _stats(d, a, default=None):
    return getattr(getattr(d, "device_stats", None), a, default)


def _latest_record(d):
    recs = getattr(d, "device_records", None) or []
    best, best_ts = None, -1
    for r in recs:
        ts = getattr(r, "timestamp", None) or 0
        if getattr(r, "pet_name", None) and ts >= best_ts:
            best, best_ts = r, ts
    return best


def _rec_content(r, a, default=None):
    return getattr(getattr(r, "content", None), a, default) if r else default


def _sprays_today(d):
    """Count today's K3 spray_over events from device_records (Purifier.spray_times
    is always 0 — the cloud doesn't maintain it; the real sprays are the events)."""
    import time
    recs = getattr(d, "device_records", None) or []
    tzoff = (getattr(d, "timezone", 0) or 0) * 3600  # device tz offset, seconds
    day_start = (int((time.time() + tzoff) // 86400)) * 86400 - tzoff
    n = 0
    for r in recs:
        for sub in (getattr(r, "sub_content", None) or []):
            if getattr(sub, "enum_event_type", None) == "spray_over":
                if (getattr(sub, "timestamp", 0) or 0) >= day_start:
                    n += 1
    return n


# --- derived values -----------------------------------------------------------
def _state_str(d):
    st = getattr(d, "state", None)
    if st is None:
        return "idle"
    ws = getattr(st, "work_state", None)
    if not ws:
        return "idle"
    mode = ws.get("workMode") if isinstance(ws, dict) else getattr(ws, "work_mode", getattr(ws, "workMode", None))
    return {0: "cleaning", 1: "dumping", 2: "odor_removal", 3: "maintenance"}.get(mode, "cleaning")


def _weight_kg(d):
    g = _st(d, "sand_weight")
    return round(g / 1000, 2) if isinstance(g, (int, float)) else None


def _error(d):
    code = _st(d, "error_code")
    if not code:
        return "no_error"
    return _st(d, "error_msg") or _st(d, "error_detail") or str(code)


def _n50_pct(d):
    days = _st(d, "deodorant_left_days")
    if not isinstance(days, (int, float)):
        return None
    return max(0, min(100, round(days / 30 * 100)))


def _pet_weight_kg(d):
    r = _latest_record(d)
    g = _rec_content(r, "pet_weight")
    return round(g / 1000, 2) if isinstance(g, (int, float)) else None


def _last_duration(d):
    r = _latest_record(d)
    ti, to = _rec_content(r, "time_in"), _rec_content(r, "time_out")
    return (to - ti) if isinstance(ti, (int, float)) and isinstance(to, (int, float)) else None


def _last_used_by(d):
    r = _latest_record(d)
    return getattr(r, "pet_name", None) or "no_record_yet" if r else "no_record_yet"


def _last_event(d):
    r = _latest_record(d)
    return getattr(r, "enum_event_type", None) or "no_events_yet" if r else "no_events_yet"


def _k3(d, a, default=None):
    return getattr(getattr(d, "k3_device", None), a, default)


# --- command factories --------------------------------------------------------
def _action(action: DeviceAction, lb: LBCommand):
    async def run(client, device, _p):
        await client.send_api_request(device.id, DeviceCommand.CONTROL_DEVICE, {action: lb})
    return run


def _reset_n50():
    async def run(client, device, _p):
        await client.send_api_request(device.id, LitterCommand.RESET_N50_DEODORIZER)
    return run


def _set(api_key: str, on_val=1, off_val=0):
    async def run(client, device, payload):
        await client.send_api_request(device.id, DeviceCommand.UPDATE_SETTING,
                                       {api_key: on_val if payload == "ON" else off_val})
    return run


def _power_cmd():
    async def run(client, device, payload):
        await client.send_api_request(device.id, DeviceCommand.POWER, 1 if payload == "ON" else 0)
    return run


def _select_sand():
    opts = {"bentonite": 1, "tofu": 2, "mixed": 3}

    async def run(client, device, payload):
        if payload in opts:
            await client.send_api_request(device.id, DeviceCommand.UPDATE_SETTING, {"sandType": opts[payload]})
    return run


SAND_REV = {1: "bentonite", 2: "tofu", 3: "mixed"}


def _sw(key, name, snake, camel, icon=None):
    """A settings switch: HA key `name`→slug, reads device.settings.<snake>, writes <camel>."""
    return Entity(key, name, "switch", category="config", icon=icon,
                  value=lambda d, s=snake: bool(_cfg(d, s)), command=_set(camel))


class PuraMaxPlugin(PetkitPlugin):
    slug = "puramax"
    name = "PetKit Pura Max / Max 2"
    handles = {"t4"}

    def entities(self, device: Any, entities_map: dict | None = None) -> list[Entity]:
        E = Entity
        ents = [
            # K3 spray counter = today's spray_over events (Purifier.spray_times is always 0)
            E("spray_times", "Spray times", "sensor", icon="mdi:spray",
              extra={"state_class": "total_increasing"}, value=_sprays_today),
            # sensors (ha-petkit-parity keys)
            E("state", "State", "sensor", icon="mdi:state-machine", value=_state_str),
            E("litter_level", "Litter level", "sensor", unit="%", icon="mdi:gauge",
              value=lambda d: _st(d, "sand_percent")),
            E("litter_weight", "Litter weight", "sensor", unit="kg", device_class="weight",
              value=_weight_kg),
            # daily visit count = device_stats.times (state.used_times resets after each clean)
            E("times_used", "Times used", "sensor", icon="mdi:counter",
              extra={"state_class": "total_increasing"},
              value=lambda d: _stats(d, "times")),
            E("average_use", "Average use", "sensor", unit="s", device_class="duration",
              extra={"state_class": "measurement"},
              value=lambda d: _stats(d, "avg_time")),
            E("total_use", "Total use", "sensor", unit="s", device_class="duration",
              extra={"state_class": "total_increasing"},
              value=lambda d: _stats(d, "total_time")),
            E("last_used_by", "Last used by", "sensor", icon="mdi:paw", value=_last_used_by),
            E("last_event", "Last event", "sensor", icon="mdi:history", value=_last_event),
            E("error", "Error", "sensor", category="diagnostic", icon="mdi:alert-circle", value=_error),
            E("pura_air_liquid", "Pura air liquid", "sensor", unit="%", icon="mdi:water-opacity",
              value=lambda d: _st(d, "liquid")),
            E("n50_odor_eliminator", "N50 odor eliminator", "sensor", unit="%", icon="mdi:scent",
              value=_n50_pct),
            E("pura_air_battery", "Pura air battery", "sensor", unit="%", device_class="battery",
              category="diagnostic", value=lambda d: _k3(d, "battery")),
            E("rssi", "Rssi", "sensor", unit="dBm", device_class="signal_strength",
              category="diagnostic", value=lambda d: getattr(_st(d, "wifi"), "rsq", None)),
            # binary
            E("wastebin", "Wastebin", "binary_sensor", device_class="problem",
              value=lambda d: bool(_st(d, "box_full"))),
            E("litter", "Litter", "binary_sensor", device_class="problem",
              value=lambda d: bool(_st(d, "sand_lack"))),
            # pet entities (renamed to sensor.rizhik_* post-deploy)
            E("pet_latest_weight", "Pet latest weight", "sensor", unit="kg", device_class="weight",
              value=_pet_weight_kg),
            E("pet_last_use_duration", "Pet last use duration", "sensor", unit="s",
              device_class="duration", value=_last_duration),
            # buttons
            E("start_resume_cleaning", "Start resume cleaning", "button", icon="mdi:broom",
              command=_action(DeviceAction.START, LBCommand.CLEANING)),
            E("odor_removal", "Odor removal", "button", icon="mdi:spray",
              command=_action(DeviceAction.START, LBCommand.ODOR_REMOVAL)),
            E("dump_litter", "Dump litter", "button", icon="mdi:delete-sweep",
              command=_action(DeviceAction.START, LBCommand.DUMPING)),
            E("turn_light_on", "Turn light on", "button", icon="mdi:lightbulb-on",
              command=_action(DeviceAction.START, LBCommand.LIGHT)),
            E("start_maintenance_mode", "Start maintenance mode", "button", icon="mdi:wrench",
              command=_action(DeviceAction.START, LBCommand.MAINTENANCE)),
            E("exit_maintenance_mode", "Exit maintenance mode", "button", icon="mdi:exit-to-app",
              command=_action(DeviceAction.END, LBCommand.MAINTENANCE)),
            E("reset_n50_odor_eliminator", "Reset n50 odor eliminator", "button", category="config",
              icon="mdi:restore", command=_reset_n50()),
            E("reset_pura_air_liquid", "Reset pura air liquid", "button", category="config",
              icon="mdi:restore", command=_set("liquidReset", on_val=1)),
            # switches
            _sw("auto_cleaning", "Auto cleaning", "auto_work", "autoWork", "mdi:autorenew"),
            _sw("periodic_cleaning", "Periodic cleaning", "fixed_time_clear", "fixedTimeClear"),
            _sw("avoid_repeat_cleaning", "Avoid repeat cleaning", "avoid_repeat", "avoidRepeat"),
            _sw("continuous_rotation", "Continuous rotation", "downpos", "downpos"),
            _sw("deep_cleaning", "Deep cleaning", "deep_clean", "deepClean"),
            _sw("light_weight_cleaning_disabled", "Light weight cleaning disabled", "underweight", "underweight"),
            _sw("kitten_mode", "Kitten mode", "kitten", "kitten"),
            _sw("auto_odor_removal", "Auto odor removal", "auto_spray", "autoSpray"),
            _sw("periodic_odor_removal", "Periodic odor removal", "fixed_time_spray", "fixedTimeSpray"),
            _sw("deep_deodorization", "Deep deodorization", "deep_refresh", "deepRefresh"),
            _sw("child_lock", "Child lock", "manual_lock", "manualLock"),
            _sw("do_not_disturb", "Do not disturb", "disturb_mode", "disturbMode"),
            E("power", "Power", "switch", category="config", icon="mdi:power",
              value=lambda d: bool(_st(d, "power")), command=_power_cmd()),
            # select
            E("litter_type", "Litter type", "select", category="config",
              options=["bentonite", "tofu", "mixed"], icon="mdi:cube-outline",
              value=lambda d: SAND_REV.get(_cfg(d, "sand_type"), "bentonite"),
              command=_select_sand()),
        ]
        return ents


PLUGIN = PuraMaxPlugin()
