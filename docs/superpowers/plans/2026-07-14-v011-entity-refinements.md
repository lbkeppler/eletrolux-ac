# v0.1.1 Entity Refinements Plan

> Tests run in WSL only: `wsl -d FedoraLinux-43 -- bash -lc 'cd /mnt/c/Users/Lucas/Documents/GitHub/eletrolux-ac && ~/electrolux-venv/bin/python -m pytest <args>'`

**Goal:** Three real-hardware refinements from user feedback on the Electrolux YI09F, all structural (no name hardcoding), validated against BOTH fixtures (YI09F + Frigidaire). Design chosen by a judge panel (hybrid).

## R1 — displayLight is a SWITCH, not a NUMBER

**Real data:** YI09F `displayLight` = `{access:readwrite, min:0, max:100, step:1, type:"string"}`, reports the token `"DISPLAY_LIGHT_0"`. User confirms it's on/off in the app. Frigidaire `displayLight` has real `values {DISPLAY_LIGHT_0, DISPLAY_LIGHT_1}` (no min/max) and is already a SWITCH.

**Fix (capabilities.py, inside the `"min" in cap and "max" in cap` branch, as a LEADING sub-branch before any numeric spec is built):**
```python
if cap_type == "string":
    # A numeric-looking range with type "string" speaks enum tokens
    # ("DISPLAY_LIGHT_0"), not integers — it's an on/off token control.
    prefix = snake_case(name).upper()   # displayLight -> "DISPLAY_LIGHT"
    lo = cap["min"]
    off = f"{prefix}_{lo}"              # "DISPLAY_LIGHT_0"
    on = f"{prefix}_{lo + 1}"          # "DISPLAY_LIGHT_1"
    if access == "readwrite":
        return EntityKind.SWITCH, {"on": on, "off": off}
    return EntityKind.BINARY_SENSOR, {"on": on, "off": off}
```
No switch.py change — its `is_on` already does `str(reported) == str(on)`, so reported `"DISPLAY_LIGHT_0"` → off (correct), turn_on writes `"DISPLAY_LIGHT_1"`. Genuine numbers (`type:"number"`: stopTime, currentEnergyUsePercent) never hit this sub-branch.

## R2 — stopTime as an hours duration NUMBER

**Real data:** YI09F `stopTime` = `{access:readwrite, min:0, max:86400, step:3600, type:"number"}`, reports `0`. It's an off-timer in seconds; 86400/3600 = 24h, step = 1h.

**Fix (capabilities.py, same branch, AFTER the string sub-branch returns and AFTER the base numeric spec is built — duration override gated on numeric type):**
```python
if cap_type in {"number", "int"} and cap["max"] >= 3600 \
        and cap["max"] % 3600 == 0 and cap.get("step", 1) % 3600 == 0:
    scale = 3600
    spec = {
        "min": cap["min"] // scale,       # 0
        "max": cap["max"] // scale,       # 24
        "step": cap.get("step", 1) // scale,  # 1
        "unit": "h",
        "device_class": "duration",
        "scale": scale,
    }
```
`currentEnergyUsePercent` (max 100, 100 % 3600 ≠ 0) and temperature caps never match. Non-duration numbers keep the plain `{min,max,step}` spec (no scale/unit).

**number.py changes:**
```python
from homeassistant.const import UnitOfTime
from homeassistant.components.number import NumberEntity, NumberDeviceClass
# in __init__:
self._scale = spec.get("scale", 1)
if spec.get("unit"):
    self._attr_native_unit_of_measurement = UnitOfTime.HOURS
if spec.get("device_class") == "duration":
    self._attr_device_class = NumberDeviceClass.DURATION
# min/max/step come from spec already in display (hours) units.
# native_value (read, seconds -> hours):
raw = coerce_value(self.appliance.reported.get(self._prop))
return None if raw is None else raw / self._scale
# async_set_native_value (write, hours -> seconds):
seconds = int(round(value * self._scale))
await self.coordinator.async_send_command(self._appliance_id, {self._prop: seconds})
```
`_scale` defaults to 1, so every non-duration number passes through unchanged.

## R3 — Skip phantom (never-reported) controls

**Real data:** YI09F `batchSchedulerMode` = `{access:readwrite, type:boolean, values:{OFF,ON}}` classifies as SWITCH but is ABSENT from reported state and doesn't exist in the app. Verified: every genuine control (even when OFF) IS in reported on both fixtures — only `batchSchedulerMode` is absent. So "absent from reported" reliably means phantom, not off-and-omitted.

**Fix:** keep the classifier PURE (don't pass reported into it). Add a present-in-reported gate in each CONTROL builder (`build_switches`, `build_selects`, `build_numbers`) — hard-SKIP, not `enabled_default=False` (a never-reported cap has no valid read/write target):
```python
reported = coordinator.data[appliance_id].reported
...
if kind is EntityKind.SWITCH and name not in reported:
    continue
```
NEVER gate SENSOR / BINARY_SENSOR / CLIMATE — only the three control kinds.

## Correctness walk (both fixtures)
- **YI09F:** displayLight → SWITCH (on=DISPLAY_LIGHT_1/off=DISPLAY_LIGHT_0, reported DISPLAY_LIGHT_0 → OFF); stopTime → NUMBER hours (0-24, reported 0 → 0.0h, set 2h → writes 7200); currentEnergyUsePercent → plain SENSOR (%, untouched); batchSchedulerMode → SKIPPED (not in reported); sleep/autoSense/comfortAir/soundVolume → switches (all in reported).
- **Frigidaire:** displayLight → SWITCH via the existing values branch (has DISPLAY_LIGHT_0/1, no min/max — the string sub-branch is only reached when min/max present, so no change); no stopTime; schedulerMode → switch (in reported); no regression.

## Tests (over BOTH fixtures)
- `test_capabilities.py`: YI09F displayLight → (SWITCH, on=DISPLAY_LIGHT_1/off=DISPLAY_LIGHT_0); YI09F stopTime → (NUMBER, spec min0/max24/step1/unit h/duration/scale3600); currentEnergyUsePercent → SENSOR with NO scale; Frigidaire displayLight still SWITCH; Frigidaire has no NUMBER.
- `test_platforms.py`: YI09F build_switches EXCLUDES batch_scheduler_mode (phantom) and display_light is NOT a number but IS a switch; build_numbers has stop_time with hours conversion (native_value of reported 0 == 0.0; set 2 → command {"stopTime": 7200}). Frigidaire switches unchanged, no numbers.
- Translations: display_light already has a switch name; ensure stop_time number name stays; remove/keep batch_scheduler_mode (now never built) — leaving its translation is harmless.

## Version bump
`manifest.json` version → `0.1.1`. Tag + release v0.1.1.
