# Troubleshooting

## Enable debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.livoltek_portal: debug
```

The integration never logs the token, the password, the MD5 digest, or full API
payloads — debug logging is safe to leave on while you reproduce a problem, and
safe to read before you paste it anywhere.

## Symptoms

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| *"The portal does not know that account"* | Wrong region | Re-add with the region whose host you see when signing in on the web |
| Repeated captcha prompts during setup | The portal is rate-limiting sign-ins | Wait a few minutes and try again |
| Captcha loop with a correct code | The image expired before you submitted it | A new image loads on each rejection; answer the newest one |
| All entities `unavailable` | Portal unreachable, or the session was revoked | Check for a repair issue under **Settings → Repairs** |
| **Online** is off and sensors are `unavailable` | The inverter is not reporting to the portal | Check the inverter's own network link; the cloud has nothing newer to serve |
| One sensor stuck on a single value | The portal stopped sending that field | The throttled warning in the log names the field |
| A sensor reads `unknown` forever | The portal never sends that field for your model | Expected; the entity exists so it can start working if firmware adds it |
| `pv_*` sensors permanently `0` | No PV array | Expected |
| Entity ids contain the inverter serial | The entry predates the naming step | Rename from the device page and accept the entity-id rewrite |

## The integration stopped polling entirely

Look under **Settings → Repairs** for *"Livoltek sign-in needs a verification
code"*. The portal demanded a captcha while renewing the session, which Home
Assistant cannot answer unattended. Open the integration and sign in again;
polling resumes without a restart.

## Values disagree with the Livoltek portal

Check `last_reported` first. It carries the inverter's own timestamp, not the
poll time — if it is minutes old, the portal and Home Assistant are looking at
the same stale cloud record and the difference is elsewhere.

`ac_power` has been observed serving a value one refresh cycle behind
`grid_power`. Compare against `grid_power`.

For battery power, mind the sign convention: **positive is charging** here. See
[Entities → Power sensor signs](entities.md#power-sensor-signs).

## Energy dashboard problems

**A total went down.** That is the failure mode worth reporting immediately —
it means a value was recorded against the wrong scale and it corrupts long-term
statistics. Open an issue with the before and after readings.

**"Unit changed" or "state class changed" in Developer tools → Statistics.**
Same category. Include the statistics entity id and the message.

**A total is missing from the dashboard's entity picker.** The dashboard only
offers `kWh` + `total_increasing` + `energy` sensors. All five documented
totals qualify; if one is missing it is almost certainly `unknown` because the
portal has not sent that field yet.

## Reporting a problem

Attach the **diagnostics** download from the integration's three-dot menu. It
redacts credentials, account ids, and hardware serials before it reaches your
disk.

Redaction works from a list of known-sensitive fields, so a genuinely new
identifying field in a future firmware payload would not be caught. Skim the
file before attaching it.

Include the Home Assistant version, the integration version, your inverter
model, and roughly when the failure happened.

[Open an issue](https://github.com/vokomarov/hass-livoltek-portal/issues).
