# Configuration

Everything is configured through the UI. There is nothing to put in
`configuration.yaml`.

## Setup flow

### 1. Region

Accounts are **not shared between portals**. Pick the host you see in the
address bar when you sign in on the web:

| Region | Host |
| --- | --- |
| EMEA | `evs.livoltek-portal.com` |
| International | `www.livoltek-portal.com` |
| Asia | `aa.livoltek-portal.com` |

Signing in against the wrong region reports *"the portal does not know that
account"* rather than a password error, because that is genuinely what the
portal says.

### 2. Credentials

The same email address or phone number and password you use in the Livoltek
app. Choose the matching account type.

Home Assistant stores an MD5 digest of the password so it can renew the session
on its own. **That digest is password-equivalent** — see
[Maintenance → Credential handling](maintenance.md#credential-handling).

### 3. Verification code

The portal sometimes demands a captcha. Home Assistant renders the image in the
form and passes your answer through. A rejected code loads a fresh image
automatically; the portal never accepts the same image twice.

### 4. Devices and polling interval

Every selected inverter becomes its own Home Assistant device with its own set
of entities.

The interval defaults to **120 seconds**. The portal's own data does not refresh
meaningfully faster than that, so shorter intervals add load and rate-limiting
risk without adding information. The minimum accepted is 30 seconds.

### 5. Names

Each device gets a name, and **that name is what every entity id is built
from**:

| Name you type | Entity ids you get |
| --- | --- |
| `Loft inverter` | `sensor.loft_inverter_battery_soc` |
| `Home battery` | `sensor.home_battery_battery_soc` |

Pick something short you can type from memory in an automation.

The default is the model name (`Hyper-6000`). It is deliberately **not** the
portal's own label, which looks like `HP1XXXXHSC1XXXXX(Hyper-6000)` and would
put the inverter serial number into every entity id, every dashboard card, and
every automation.

Two rules are enforced:

- A name must contain at least one letter or digit.
- Two devices may not produce the same entity id prefix. `Loft Inverter` and
  `loft inverter` are two names but one prefix, and Home Assistant would
  silently append `_2` to the second device's entities.

## Changing things later

**Settings → Devices & services → Livoltek Portal → Configure** reopens the
device selection and the polling interval. Changes apply without a restart.

**Renaming is not there, on purpose.** Home Assistant applies a changed device
name to the device registry but does not move entity ids that were already
generated from the old name — an options rename would look like it worked while
every automation kept pointing at the old ids. Use the device page's own
**rename** button instead: it offers to rewrite the entity ids too, which is the
part that matters.

## Re-authentication

The portal issues a 30-day token and offers no refresh endpoint. The integration
decodes the token's own expiry, signs in again about three days before it
lapses, and retries once if a call comes back unauthorised.

If the portal demands a captcha during an automatic sign-in, Home Assistant
cannot answer it on its own. A repair issue appears and polling pauses until you
re-authenticate from **Settings → Devices & services**.

## Multiple accounts

Add the integration again for a second Livoltek account. Each account is a
separate config entry, keyed on the portal's owner id, so the same account
cannot be added twice.
