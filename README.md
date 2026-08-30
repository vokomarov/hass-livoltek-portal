# Livoltek Portal for Home Assistant

[![CI](https://github.com/vokomarov/hass-livoltek-portal/actions/workflows/ci.yml/badge.svg)](https://github.com/vokomarov/hass-livoltek-portal/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/vokomarov/hass-livoltek-portal)](https://github.com/vokomarov/hass-livoltek-portal/releases)
[![HACS: custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/)

Polls the Livoltek cloud portal and exposes a hybrid inverter's energy storage
telemetry to Home Assistant: battery state of charge and status,
battery/grid/load/PV/backup power, and the lifetime totals the Energy dashboard
needs.

Not affiliated with, endorsed by, or supported by Livoltek. The portal API is
undocumented and may change without notice.

## Motivation

I ran [adamlonsdale/hass-livoltek](https://github.com/adamlonsdale/hass-livoltek)
for a long time and it did the job. Through 2026 it started breaking. The fault
was not in that integration but in the official API Livoltek publishes behind
it, which goes down for long stretches and, when it does answer, often returns
values that are stale or plainly wrong.

The part I could not get past is that the Livoltek portal kept working through
every one of those outages. The data was there. Only the official API could not
reach it.

I opened several support tickets with Livoltek. None were answered, and the
official API still behaves badly for me today.

So this integration signs in to the portal with your own account and reads the
same figures the portal shows you.

> [!WARNING]
> Livoltek publishes no specification for what the portal returns, and can
> change it at any time without warning. That is the trade: you get the data the
> portal shows you, and it can break without notice.
>
> **I am not responsible for anything that happens to your hardware as a result
> of using this integration.** Every call it makes today is read only, so it
> reads your system and writes nothing back. That may not stay true: the portal
> exposes configuration too, and some of it may be worth adding here.
>
> The integration is provided as is, and it is free under the
> [MIT licence](LICENSE). I will keep it maintained for as long as I can keep it
> in good shape. Feature requests are welcome, but none of them are guaranteed.

## Install

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=vokomarov&repository=hass-livoltek-portal&category=integration)

Requires Home Assistant 2025.2.0 or newer, [HACS](https://hacs.xyz/), and a
Livoltek portal account. Full steps, including manual installation, are in
[docs/installation.md](docs/installation.md).

Then **Settings → Devices & services → Add integration → Livoltek Portal** and
follow [the setup walkthrough](docs/configuration.md).

## What you get

Per selected inverter: **38 sensors** enabled by default, one **Online** binary
sensor, and **18 diagnostic sensors** created disabled. Full list with units and
device classes: [docs/entities.md](docs/entities.md).

- **Energy dashboard ready** — five `kWh` / `total_increasing` totals map
  straight into the dashboard's slots. [Mapping](docs/entities.md#energy-dashboard).
- **Stable units** — the portal rescales fields between kWh and MWh at the 1000
  boundary; the integration normalises before Home Assistant sees a value, so
  long-term statistics never take a 1000× jump.
- **Readable status** — `battery_status` reports `charging`, `idle`, or
  `discharging`, not the portal's `1` / `0` / `-1`.
- **Entity ids you choose** — setup asks for a device name, so you get
  `sensor.loft_inverter_battery_soc` rather than the inverter's serial number.
- **No gaps on partial data** — a field the portal drops holds its last value
  with a logged warning instead of publishing a hole.

## Security

**The stored credential is password-equivalent.** The portal authenticates with
an unsalted, uniterated MD5 digest of your password and accepts that digest in
place of the password. Home Assistant stores it, with the session token, in
`config/.storage/core.config_entries` — plaintext JSON on disk. Anyone who can
read that file, or an unencrypted backup of it, can sign in to your Livoltek
account.

This is a property of the portal's API, not something this integration can fix.
Use a password unique to Livoltek and encrypt your backups —
[details and mitigations](docs/maintenance.md#credential-handling).

## Documentation

| | |
| --- | --- |
| [Installation](docs/installation.md) | Requirements, HACS, manual, updating, removing |
| [Configuration](docs/configuration.md) | Regions, sign-in, device names, changing settings later |
| [Entities](docs/entities.md) | Every sensor, Energy dashboard mapping, sign conventions |
| [Troubleshooting](docs/troubleshooting.md) | Debug logging, symptoms, reporting a problem |
| [Maintenance](docs/maintenance.md) | Updates, rollback, backups, credentials |
| [Development](docs/development.md) | Layout, tests, API notes, releasing |

## Contributing

Issues and pull requests are welcome. Run `ruff check .` and `pytest` before
opening one — see [docs/development.md](docs/development.md).

**Never post raw API captures.** They carry tokens, account ids, and hardware
serials. The diagnostics download from the integration's three-dot menu is
redacted; attach that instead.

## Legal

An independent project, written for interoperability. Not affiliated with,
endorsed by, or supported by Livoltek, and not a Livoltek product. "Livoltek"
and every other name used here belongs to its owner and appears only to say what
this software connects to.

The integration signs in to the Livoltek portal with credentials you supply for
your own account, reads data about your own hardware, and keeps it on your own
Home Assistant instance. It only reads: it issues no commands, changes no
settings, and never touches firmware. Nothing it collects reaches me or anyone
else. When the portal asks for a verification code it shows you the image and
you answer it; nothing here works around that.

If Livoltek considers anything in this repository a problem, please
[open an issue](https://github.com/vokomarov/hass-livoltek-portal/issues) and I
will respond.

## Licence

[MIT](LICENSE).
