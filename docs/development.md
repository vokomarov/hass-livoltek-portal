# Development

## Layout

```
custom_components/livoltek_portal/
  __init__.py        Entry setup, unload, reload, runtime data
  config_flow.py     Region, sign-in, captcha, device selection, naming, options
  captcha.py         Serves the captcha image to the config-flow form
  coordinator.py     Polling, staleness, fail-open value holding
  entity.py          Shared device identity and availability
  sensor.py          The sensor table -- one row per entity
  binary_sensor.py   The Online sensor
  diagnostics.py     Redacted diagnostics dump
  const.py           Domain, regions, config keys, timing constants
  api/
    transport.py     HTTP, envelope unwrapping, error mapping
    auth.py          Login, MD5 digest, token expiry decoding
    client.py        Endpoint methods
    models.py        Session, DeviceRef
    units.py         Unit families and normalisation
    errors.py        Exception hierarchy
```

The API layer is vendored rather than declared as a `requirements` entry in the
manifest, so a HACS install never has to resolve a package at runtime.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt ruff
```

## Checks

```bash
source .venv/bin/activate
ruff check .
pytest -q
```

Both run in CI on every push and pull request, alongside **hassfest** and
**HACS** validation. Snapshots live in `tests/snapshots/`; regenerate with
`pytest --snapshot-update` and read the diff before committing it.

Some tests exist to protect things no runtime check covers:

| Test | Protects |
| --- | --- |
| `test_docs.py` | `docs/entities.md` matching the actual entity list |
| `test_repo_metadata.py` | Manifest, `hacs.json`, and documented risk disclosure |
| `test_sensor.py` invariants | Unit/device-class/state-class consistency per row |

## Working with the portal API

The integration calls four endpoints on the Livoltek portal, all of them reads,
using the account holder's own credentials:

| Endpoint | Purpose |
| --- | --- |
| `POST /nbp/login/customer` | sign in as the account holder |
| `GET /nbp/image/code` | fetch the captcha image when the portal asks for one |
| `GET /ctrller-manager/energystorage/findAllByCustomer` | list the account's own devices |
| `GET /ctrller-manager/app/energystorage/energyStorageInfo` | read one device's telemetry |

Nothing is written, and no other endpoint is called. The portal publishes no
specification for these, so everything below was learned from its responses.

Two rules hold when working on this:

**Never call live endpoints with someone else's credentials.** A question that
needs real hardware goes to the account holder as a worksheet: what to run, what
to expect, and a table for the result. Those worksheets stay out of this
repository.

**Raw captures never enter git.** A capture can carry tokens, serials, and
account data. Quoting one in an issue means redacting serials to the
`HP1XXXXHSC1XXXXX` form first.

The payload quirks worth knowing: `gird` is the vendor's spelling of *grid*,
every response is HTTP 200 regardless of outcome so success is signalled by
`msg_code` alone, and units are rescaled per field unless you pass
`isUseChangeUnit=false`.

## Releasing

1. **Releases → Draft a new release.**
2. Under *Choose a tag*, type the new one — `v0.2.0` — and let GitHub create it
   on publish.
3. Click **Generate release notes**. `.github/release.yml` sorts them into
   categories by pull-request label.
4. **Publish release.**

Publishing is the trigger. The workflow reads the version from the tag, stamps
it into `manifest.json`, builds the ZIP, attaches it, and appends the standing
install instructions from `.github/release-footer.md` to whatever notes you
published.

Nothing is prepared by hand and nothing is pushed to `main`, so `main` can be
protected with no exemptions for the Actions bot.

**The manifest version in git is not the released version.** It is stamped into
the archive at release time and never committed back, so `main` carries whatever
the previous release left there. The tag is the only source of truth. This is
what `hacs/integration`, `spook`, and `powercalc` all do — do not "fix" the
stale value in a pull request.

A tag that is not `vX.Y.Z` (optionally `a1`, `b1`, `rc1`) fails the first step
before anything is published. Delete the release and the tag, then draft it
again.

Because `hacs.json` sets `zip_release`, HACS installs the ZIP asset rather than
the repository tree. A release without that asset is not installable, which is
why the job builds and attaches it in the same run that creates the release.

## Manual verification

Unit tests cannot exercise a real inverter. Before a release that touches
polling, units, or the config flow, work through
[the end-to-end checklist](e2e-checklist.md) against real hardware and record
the results.
