# Dev notes — PetKit cloud model & command mechanism

Reverse-engineered from `pypetkitapi` 1.27.0 against the live account (Pura Max 2,
device 400106386, `device_type=t4`, fw 1.652). These drive the `puramax` plugin.

## Client

```python
from pypetkitapi.client import PetKitClient
c = PetKitClient(username, password, region="UA", timezone="Europe/Kyiv", session=aiohttp_session)
await c.get_devices_data()           # populates c.petkit_entities {id: device}
await c.send_api_request(device_id: int, action: StrEnum, setting: dict|int|None) -> bool
```

Account has: Litter (`t4`), Purifier(s) (the K3 `AIR SMART SPRAY`, `relate_t4`→box), Pet.

## Litter device — fields (snake_case model attrs)

**top-level:** `id, name, sn, firmware, hardware, mac, bt_mac, with_k3, k3_device,
in_times, last_out_time, total_time, maintenance_time, device_nfo, state, settings,
device_stats, device_records[], pet_out_records[]`

**`state` (StateLitter) → sensors:**
`sand_percent` (litter %), `sand_weight` (g), `sand_type`, `sand_lack`, `used_times`,
`box`/`box_full`/`box_state` (waste bin), `battery`, `liquid` (Pura Air liquid %),
`liquid_lack`/`liquid_empty`, `deodorant_left_days`, `spray_days`/`spray_left_days`,
`error_code`/`error_msg`/`error_detail`/`error_level`, `low_power`, `power`, `pim`,
`work_state`, `overall`, `pet_in_time`, `frequent_restroom`, `wifi`.

**`settings` (SettingsLitter) → switches/selects (API keys are camelCase!):**
`auto_work`→`autoWork`, `avoid_repeat`→`avoidRepeat`, `deep_clean`→`deepClean`,
`kitten`, `downpos`, `bury`, `underweight`, `manual_lock`→`manualLock`,
`disturb_mode`→`disturbMode`, `auto_spray`→`autoSpray`, `deep_refresh`→`deepRefresh`,
`relate_k3_switch`→`relateK3Switch`, `sand_type`→`sandType` (1 bentonite/2 tofu/3 mixed),
`unit` (0 kg/1 lb), `language`, `still_time`, `stop_time`, `auto_interval_min`.

**`device_stats` (LitterStats):** `times`, `avg_time`, `total_time`, `statistic_info[]`.

**`device_records[]` (LitterRecord) — RICHER than ha-petkit exposes:** per visit
`content.pet_weight` (g), `time_in`/`time_out`, `pet_id`/`pet_name`; sub-events
`clean_over`/`spray_over` with `litter_percent`, and health fields
`urine_bolus`/`soft_stools`/`hard_stools`/`ph_state`/`ph_reason`. → feed health monitoring.

## Commands (from `pypetkitapi/command.py` ACTIONS_MAP)

- **Change a setting:** `send_api_request(id, DeviceCommand.UPDATE_SETTING, {"autoWork": 1})`
  → API params `{"id": id, "kv": json(setting)}`. Use camelCase keys above.
- **Reset N50 deodorizer:** `send_api_request(id, LitterCommand.RESET_N50_DEODORIZER)`
  (`= "reset_deodorizer"`).
- **Actions (clean/dump/maintenance/odor/light):** `DeviceCommand.CONTROL_DEVICE`,
  params `{"id": id, "kv": json(command), "type": list(command)[0].split("_")[0]}`,
  supported for T4. `command` is a dict whose key encodes the action; values come from
  `LBCommand` (IntEnum: CLEANING, DUMPING, MAINTENANCE, ODOR_REMOVAL, LIGHT,
  RESET_N50_DEODOR, LEVELING, CALIBRATING, RESETTING).
  ⚠️ TODO: confirm the EXACT control dict shape for the litter (e.g. `{"start_action": n}`
  vs `{"stop_action": n}`) from Jezza34000 HA integration `button.py`/`litter` actions
  before wiring the clean/dump/maintenance buttons live.
```
