# End-to-end verification

Run against a real Home Assistant instance with a real Livoltek account, after
the unit suite is green. Record the result of each check inline; an unrecorded
check is a check that did not happen.

Environment: Home Assistant on the NAS, the integration installed from the git
repository (HACS custom repository, or copied into `custom_components/`).

## 1. Install and discover

- [ ] The integration appears in **Add integration** after a restart
- [ ] No error in the log at startup
- [ ] The region dropdown lists all three portals

## 2. Sign in

- [ ] Correct credentials reach the device step
- [ ] A deliberately wrong password shows "the portal rejected that account or
      password" and does not create an entry
- [ ] A deliberately wrong region shows the region hint
- [ ] If a captcha appears: the image renders in the form, a correct code is
      accepted, a wrong code re-renders with a *different* image

## 3. Device selection

- [ ] The real inverter is listed with a readable label
- [ ] The naming step defaults to the model name, not the serial-bearing portal
      label, and a name with no letters or digits is rejected
- [ ] Selecting it creates one Home Assistant device, named as typed
- [ ] Every entity id starts with that name and contains no serial number
- [ ] `model`, `sw_version`, `hw_version`, and `serial_number` are populated on
      the device page

## 4. Entities and values

- [ ] 38 enabled sensors plus the Online binary sensor exist
- [ ] Battery status reads `Charging`, `Idle`, or `Discharging` — never a number
      and never `unknown` — and matches which way the portal's battery arrow
      points
- [ ] Battery SoC matches the Livoltek portal within one percent
- [ ] Battery power, grid power, load power, and PV power match the portal's
      current figures
- [ ] Every energy total is in kWh — no sensor shows MWh or Wh
- [ ] `last_reported` is a plausible recent timestamp
- [ ] Enabling one diagnostic sensor produces a value after the next poll

## 5. Energy dashboard

- [ ] All five statistics entities are offered in the dashboard configuration
- [ ] Note each of the five totals now, wait at least 6 hours, then read them
      again. Every one must be greater than or equal to its earlier value,
      and at least one must have increased. A total that went *down* is the
      failure this step exists to catch: it means the value is being recorded
      against the wrong scale or state class, and it corrupts long-term
      statistics silently. Report the before and after numbers, not just a
      pass.

      Which one increases depends on the site. On a PV site, wait across some
      daylight and expect `pv_energy_total` to move. On a grid-charged UPS
      site with no array — the reference setup here — `pv_energy_total` and
      `grid_exported_total` stay flat forever and that is correct, not a
      failure; expect `grid_imported_total` to move, and
      `battery_charged_total` / `battery_discharged_total` to move only if
      the battery actually cycled in the window. If nothing moved at all,
      the window was too quiet to prove anything — repeat it rather than
      recording a pass.
- [ ] `developer tools -> statistics` reports no "unit changed" or "state class
      changed" issue for any Livoltek entity

## 6. Fail-open behaviour

- [ ] Disconnect the NAS from the internet: entities go unavailable, the log
      shows an update failure, and no entity value is corrupted
- [ ] Reconnect: values resume within one poll interval with no restart
- [ ] Overnight, PV power reads exactly `0` rather than becoming unavailable or
      holding the previous daylight value

## 7. Session and reload

- [ ] Reloading the entry does not require signing in again
- [ ] Restarting Home Assistant does not require signing in again
- [ ] Changing the polling interval in options applies without a restart, and
      the coordinator's interval visibly changes
- [ ] Removing the entry removes every device and entity

## Recording results

Keep anomalies, log excerpts, and screenshots outside the repository — they
carry tokens, serials, and account data. Only a redacted summary belongs in an
issue or the release notes.
