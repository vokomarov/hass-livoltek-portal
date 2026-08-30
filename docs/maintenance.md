# Maintenance

## Updating

HACS surfaces an update when a release is published. Apply it and restart Home
Assistant. Config entries, device names, entity ids, and recorded statistics all
survive an update — you are not asked to sign in again.

Read the release notes before updating anyway. Anything that changes a unit,
state class, or entity id is called out there, because those are the changes
that can disturb existing statistics and automations.

## Rollback

1. **HACS → Livoltek Portal → three-dot menu → Redownload**
2. Choose the previous version from the version list
3. Restart Home Assistant

Downgrading does not undo changes a newer version made to the config entry. If a
release adds a stored field, an older version simply ignores it.

## Backups

The integration keeps no state of its own outside Home Assistant's config entry
storage, so a normal Home Assistant backup covers it. Two files matter:

| File | Contains |
| --- | --- |
| `config/.storage/core.config_entries` | Credential digest, session token, device names |
| `config/.storage/core.entity_registry` | Entity ids and enabled/disabled state |

**Encrypt your backups.** The first of those is enough to sign in to your
Livoltek account — see below.

## Credential handling

**The stored credential is password-equivalent.** The portal authenticates with
an unsalted, uniterated MD5 digest of your password, and it accepts that digest
in place of the password itself. Home Assistant stores the digest and the
session token in `config/.storage/core.config_entries` — plaintext JSON on disk.

Anyone who can read that file, or an unencrypted backup containing it, can sign
in to your Livoltek account. This is a property of the portal's API, not
something this integration can fix or work around.

Practical mitigations:

- Use a password unique to Livoltek.
- Encrypt Home Assistant backups.
- Restrict filesystem and SSH access to the Home Assistant host.
- Delete the config entry if you stop using the integration; that removes the
  stored digest.

The integration never logs the token, the password, the digest, or full API
payloads. Diagnostics dumps redact credentials, account ids, and hardware
serials before you download them.

## Session lifetime

The portal issues a 30-day token and provides no refresh endpoint. The
integration decodes the token's own expiry and signs in again about three days
before it lapses. Nothing needs doing on your side unless the portal demands a
captcha during that renewal, which raises a repair issue — see
[Troubleshooting](troubleshooting.md#the-integration-stopped-polling-entirely).

## Rotating your Livoltek password

Change it on the Livoltek portal, then re-authenticate in Home Assistant:
**Settings → Devices & services → Livoltek Portal → Reconfigure**. The old
digest is replaced; there is no need to delete and re-add the entry, and entity
ids are unaffected.

## Removing everything

Delete the config entry (**Settings → Devices & services → Livoltek Portal →
Delete**), then uninstall from HACS. That removes devices, entities, and the
stored credential.

Long-term statistics survive deletion of the entry. Remove them from
**Developer tools → Statistics** if you want them gone as well.
