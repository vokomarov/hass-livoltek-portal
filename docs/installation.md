# Installation

Livoltek Portal is a **custom integration**, not an add-on. It installs into
`custom_components/livoltek_portal/` in your Home Assistant configuration
directory and runs inside Home Assistant itself.

- Home Assistant **2025.2.0** or newer
- A Livoltek portal account with at least one energy storage device
- Outbound HTTPS from Home Assistant to your regional portal host

## Recommended installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=vokomarov&repository=hass-livoltek-portal&category=integration)

**[Add Livoltek Portal to HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=vokomarov&repository=hass-livoltek-portal&category=integration)**

1. Select the button above. It opens HACS on your own Home Assistant with this
   repository already filled in.
2. Select **Download**, then restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**.
4. Search for **Livoltek Portal** and follow the setup flow described in
   [Configuration](configuration.md).

The button needs the [My Home Assistant](https://my.home-assistant.io/) redirect
service to be enabled, which it is by default. If nothing happens, use the
manual HACS route below.

## HACS, without the button

1. **HACS → three-dot menu → Custom repositories**
2. Repository: `https://github.com/vokomarov/hass-livoltek-portal`, type
   **Integration**
3. **Download** Livoltek Portal, then restart Home Assistant
4. **Settings → Devices & services → Add integration → Livoltek Portal**

## Manual installation

Use this only if you do not run HACS. There is no update notification on this
route — you have to check for releases yourself.

1. Download `livoltek_portal.zip` from the
   [latest release](https://github.com/vokomarov/hass-livoltek-portal/releases/latest).
2. Unpack it into `config/custom_components/livoltek_portal/` so that
   `manifest.json` sits directly inside that directory.
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → Livoltek Portal**

## Updating

HACS shows an update when a new release is published; apply it and restart.
Configuration survives updates — you are not asked to sign in again.

See [Maintenance](maintenance.md) for rollback and backup guidance.

## Removing

**Settings → Devices & services → Livoltek Portal → three-dot menu → Delete**.
That removes every device, entity, and the stored credential. Uninstall the
repository in HACS afterwards to remove the files.

Long-term statistics recorded by the Energy dashboard are *not* deleted with the
entry. Remove those from **Developer tools → Statistics** if you want them gone.
