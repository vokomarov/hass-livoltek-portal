# Entities

Every selected inverter becomes one device carrying **38 sensors enabled by
default**, one **Online** binary sensor, and **18 diagnostic sensors** created
disabled.

Entity ids are `sensor.<device>_<key>`, where `<device>` is the name you chose
during setup — see [Configuration → Names](configuration.md#5-names). The keys
below are the second half.

A sensor is created whether or not the portal currently reports the field. A
field the portal never sends reads `unknown`, not `unavailable`, so the entity
is still there when the firmware starts sending it.

## Battery

| Key | Unit | Device class | State class |
| --- | --- | --- | --- |
| `battery_soc` | `%` | battery | measurement |
| `battery_power` | `kW` | power | measurement |
| `battery_status` | — | enum | — |
| `battery_voltage` | `V` | voltage | measurement |
| `battery_current` | `A` | current | measurement |
| `battery_max_temperature` | `°C` | temperature | measurement |
| `battery_min_temperature` | `°C` | temperature | measurement |
| `battery_charged_today` | `kWh` | energy | total_increasing |
| `battery_charged_total` | `kWh` | energy | total_increasing |
| `battery_discharged_today` | `kWh` | energy | total_increasing |
| `battery_discharged_total` | `kWh` | energy | total_increasing |

`battery_soc` is read from the portal's `batteryRestSoc`, not its `batterySOC` —
the latter is `null` in every payload observed.

**`battery_status`** reports `charging`, `idle`, or `discharging` rather than the
portal's `1` / `0` / `-1`, so an automation reads:

```yaml
condition: state
entity_id: sensor.loft_inverter_battery_status
state: discharging
```

A status value the portal invents in a future firmware reports as `unknown`
rather than breaking the entity.

## Grid

| Key | Unit | Device class | State class |
| --- | --- | --- | --- |
| `grid_power` | `kW` | power | measurement |
| `grid_imported_today` | `kWh` | energy | total_increasing |
| `grid_imported_total` | `kWh` | energy | total_increasing |
| `grid_exported_today` | `kWh` | energy | total_increasing |
| `grid_exported_total` | `kWh` | energy | total_increasing |
| `grid_voltage` | `V` | voltage | measurement |
| `grid_current` | `A` | current | measurement |
| `grid_frequency` | `Hz` | frequency | measurement |

## Load and backup

| Key | Unit | Device class | State class |
| --- | --- | --- | --- |
| `load_power` | `kW` | power | measurement |
| `load_consumption_today` | `kWh` | energy | total_increasing |
| `load_consumption_total` | `kWh` | energy | total_increasing |
| `load_energy_used_today` | `kWh` | energy | total_increasing |
| `load_energy_used_total` | `kWh` | energy | total_increasing |
| `load_voltage` | `V` | voltage | measurement |
| `load_current` | `A` | current | measurement |
| `backup_power` | `kW` | power | measurement |
| `backup_voltage` | `V` | voltage | measurement |
| `backup_current` | `A` | current | measurement |
| `backup_energy_total` | `kWh` | energy | total_increasing |

The backup (EPS) sensors describe the protected-circuits output. On grid it is a
subset of the load; off grid the two are equal, because off grid every load is a
protected load.

## Solar

| Key | Unit | Device class | State class |
| --- | --- | --- | --- |
| `pv_power` | `kW` | power | measurement |
| `pv_energy_today` | `kWh` | energy | total_increasing |
| `pv_energy_total` | `kWh` | energy | total_increasing |

On a site with no array these stay at `0` permanently. That is correct, not a
fault.

## Inverter

| Key | Unit | Device class | State class |
| --- | --- | --- | --- |
| `ac_power` | `kW` | power | measurement |
| `reactive_power` | `kvar` | reactive_power | measurement |
| `inverter_temperature` | `°C` | temperature | measurement |
| `total_runtime` | `h` | duration | total_increasing |
| `last_reported` | — | timestamp | — |

`ac_power` duplicates `grid_power` and has been observed serving a stale value
once. Prefer `grid_power`.

`last_reported` is the inverter's own `updateTime` as reported by the portal,
not the time Home Assistant polled. It is what the **Online** binary sensor and
entity availability are computed from.

## Binary sensor

| Key | Device class | Meaning |
| --- | --- | --- |
| `online` | connectivity | The inverter has reported recently |

`binary_sensor.<device>_online` turns **off** when the inverter stops reporting,
and stays *available* while doing so, precisely so an automation can act on it.
The sensors go `unavailable` in the same situation.

An inverter counts as stale after three polling intervals, with a floor of 15
minutes so a normally-slow inverter does not flap.

## Diagnostic sensors

Created **disabled**. Enable individually from the device page; a value appears
after the next poll.

| Key | Unit | Notes |
| --- | --- | --- |
| `battery_capacity` | `kWh` | Nameplate storage capacity |
| `battery_module_count` | — | Number of battery modules |
| `battery_serial_number` | — | Battery pack serial |
| `bms_capacity` | `Ah` | BMS-reported capacity |
| `bms_version` | — | BMS firmware version |
| `cell_voltage_max` | `V` | Highest cell voltage |
| `cell_voltage_min` | `V` | Lowest cell voltage |
| `bus_voltage` | `V` | DC bus voltage |
| `inverter_frequency` | `Hz` | Inverter output frequency |
| `signal_strength` | `%` | Cloud link signal strength |
| `capacity_level` | — | Vendor capacity code |
| `pcs_status` | — | Raw vendor status integer |
| `work_status` | — | Raw vendor status integer |
| `arm_version` | — | ARM firmware version |
| `master_dsp_version` | — | Master DSP firmware version |
| `slave_dsp_version` | — | Slave DSP firmware version |
| `wifi_version` | — | Wi-Fi module firmware version |
| `wifi_serial_number` | — | Wi-Fi module serial |

`pcs_status` and `work_status` stay raw integers deliberately. They were
identical across every observed operating state — charging, idle, and
discharging — and changed only when the cloud served a stale record, so there is
no operating mode to name them after. The `Online` sensor already reports
freshness.

## Energy dashboard

**Settings → Dashboards → Energy**, then map:

| Dashboard slot | Entity |
| --- | --- |
| Grid consumption | `sensor.<device>_grid_imported_total` |
| Return to grid | `sensor.<device>_grid_exported_total` |
| Solar production | `sensor.<device>_pv_energy_total` |
| Battery in | `sensor.<device>_battery_charged_total` |
| Battery out | `sensor.<device>_battery_discharged_total` |

All five are `kWh` / `total_increasing`, which is what the dashboard requires.

The portal rescales units per field — the same account can report today's import
in kWh and the lifetime import in MWh. The integration converts everything to a
fixed unit before it reaches Home Assistant, because a unit that flips at the
1000 boundary would write a 1000× jump into long-term statistics and corrupt the
dashboard permanently.

## Power sensor signs

Instantaneous power is published exactly as the portal reports it, with no sign
transformation:

| Sensor | Positive | Negative |
| --- | --- | --- |
| `battery_power` | Charging | Discharging |
| `grid_power` | Importing | Exporting (unverified) |
| `load_power`, `backup_power`, `pv_power` | Always positive | — |

`battery_power` is **positive while charging**. Home Assistant enforces no sign
convention here and shipped integrations disagree with each other — Tesla
Powerwall is negative-while-charging, Fronius is positive — so this integration
matches the vendor's own app rather than picking a side. If you want the
opposite, a template sensor negating it is two lines on your end.

None of this affects the Energy dashboard, which reads the cumulative `_total`
counters rather than any instantaneous sensor.

The export direction of `grid_power` is **unverified**: it was confirmed against
hardware that cannot export, so only the import sign was observable. If you have
an exporting site and it reads wrong, please
[open an issue](https://github.com/vokomarov/hass-livoltek-portal/issues) — the fix is
one line.

## Missing values

If the portal returns a field as `null`, an empty string, or with an
unrecognised unit, the integration keeps the previous value and logs a warning
rather than publishing a gap. **Zero is a real reading** and always updates. A
held value is released after roughly ten polls, or thirty minutes, whichever is
longer.
