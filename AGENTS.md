# AGENTS.md

A Home Assistant custom integration that polls the Livoltek portal and exposes
one hybrid inverter's energy storage telemetry. Domain `livoltek_portal`.
Python, no runtime dependencies beyond Home Assistant itself: the API client is
vendored under `custom_components/livoltek_portal/api/`.

Read [docs/development.md](docs/development.md) first. It has the file layout,
the four endpoints, the payload quirks, and the release process. This file
covers only what is not in there.

## Rules that are not negotiable

**Never call a live portal endpoint with someone else's credentials.** There is
no test account. A question that can only be answered by real hardware becomes a
markdown worksheet for the account holder: what to run, what to expect, and a
table for the result. Worksheets stay out of this repository.

**Raw captures never enter git.** A response body carries a session token, an
account id, and a hardware serial. Redact serials to the `HP1XXXXHSC1XXXXX`
form before quoting one anywhere, including in an issue.

**Research material lives outside the repository.** `.gitignore` blocks
`docs/api/`, `docs/probes/`, and `docs/superpowers/`. Do not re-add them, and do
not commit notes, captures, or specs into `docs/` under other names.

**The integration is read only.** Four endpoints, all GETs plus the login POST.
Adding a write, a control, or a configuration call is not a routine change: it
moves the project into a different risk class and needs an explicit decision
from the maintainer first.

## Checks

```bash
source .venv/bin/activate
ruff check .
pytest -q
```

Both gate every push and pull request, alongside hassfest and HACS validation.
Snapshots live in `tests/snapshots/`; regenerate with `pytest --snapshot-update`
and read the diff before committing it.

Three test files exist to catch what no runtime check covers: `test_docs.py`
(the entity table matches the actual entities, and every relative doc link
resolves), `test_repo_metadata.py` (manifest, `hacs.json`, risk disclosure), and
the invariant tests in `test_sensor.py` (unit, device class, and state class
agree per row).

Adding or renaming a sensor means updating `docs/entities.md` in the same
change, including the counts in its header sentence (`test_docs.py` fails
otherwise), and bumping the hard-coded totals in
`test_sensor.py::test_the_table_has_the_expected_shape` (row count and
enabled-by-default count), then regenerating snapshots.

## Git strategy

`main` is the only long-lived branch. There is no develop branch and no release
branch: a release is a tag on `main`, and everything else is a short branch that
exists until its pull request merges.

Never commit to `main`, and never push to it. Every change goes through a pull
request, including a one-line documentation fix.

### Branches

Branch off the current `main`. Name the branch for the change, not for the
person or the ticket: `fix/battery-status-unknown`, `feat/grid-import-sensor`,
`docs/entities-table`. Delete it after the merge, which GitHub does for you.

One branch is one change. A branch that fixes a bug and also renames three
files is two pull requests that were not split.

### Commits

Conventional Commits, lower case after the colon, imperative mood:

```
feat: expose the backup circuit power sensor
fix: hold the last value when the portal drops a field
docs: explain the unit rescaling in the entities table
ci: pin every action to a commit SHA
chore: drop the unused units helper
build(deps): bump actions/checkout from 4 to 7
```

Types in use: `feat`, `fix`, `docs`, `ci`, `chore`, `build(deps)`. Add a scope
only when it disambiguates.

The subject is what a stranger reads in a changelog, so say what changed, not
where you were working. The body explains why, and wraps at 72 columns. Anything
that changes an entity id, a unit, or a state class says so in the body, because
it breaks existing statistics for every user.

**Every commit is signed.** The repository rejects unsigned commits on `main`.

### Pull requests

The title is the squashed commit's subject, so it follows the same Conventional
Commits rule. The description says what changed and why; skip a test plan
section unless you actually ran the steps in it.

Label the pull request. `.github/release.yml` sorts generated release notes by
label, and an unlabelled pull request lands in "Other changes":

| Label | For |
| --- | --- |
| `breaking-change` | changes a unit, state class, or entity id |
| `enhancement`, `feature` | new entity, new option, improved behaviour |
| `bug`, `fix` | corrects a defect |
| `documentation` | docs, README, release notes |
| `chore`, `ci`, `dependencies` | housekeeping, workflows, version bumps |
| `skip-changelog` | keep it out of the notes entirely |
| `needs-diagnostics` | waiting on a redacted diagnostics download |
| `upstream-api` | caused by portal behaviour, not by this integration |

Four checks must pass before merge: `lint`, `test`, `hassfest`, `hacs`. The
branch must also be up to date with `main` — the ruleset is strict, so a stale
branch is rebased, not merged into.

### Review

`.github/CODEOWNERS` makes @vokomarov the owner of every path, and the ruleset
requires a code owner's approval, one approving review, all review threads
resolved, and re-approval after any new push.

GitHub does not let you approve your own pull request. As the sole owner,
@vokomarov merges through the repository's admin bypass rather than by
satisfying the review rule. Everyone else needs the review. If a second
maintainer ever appears, the bypass should go.

### Merging

Squash only. Merge commits and rebase merges are disabled, and `main` requires
linear history. The merge commit takes the pull request title as its subject and
the commit messages as its body.

### Actions

Every GitHub Action is pinned to a full commit SHA, and the repository enforces
it. A tag or branch reference is rejected. Dependabot proposes the bumps monthly
and labels them `dependencies` and `ci`.

### Releases

Tags are the only thing that triggers a release, and nothing is ever pushed to
`main` to make one. Draft a release, tag it `vX.Y.Z`, publish, and the workflow
stamps the version into `manifest.json`, builds the ZIP, and attaches it. The
version committed in `manifest.json` is not the released version and should not
be "fixed" in a pull request. Full procedure:
[docs/development.md](docs/development.md#releasing).

**Writing the notes.** Draft them with the `humanizer` skill, and use emoji to
head the sections — release notes are the one place in this repo where emoji are
wanted. 📝 Save the draft to `worksheets/release-notes-vX.Y.Z.md` (git-ignored),
never under `docs/`. Put a short **Highlights** section and, when the change
needs the user to act (re-map an Energy dashboard slot, re-enable an entity), an
**Action for existing installs** section *above* the auto-generated
"What's Changed" list. The `## Install` / `## Documentation` footer is appended
by the workflow from `.github/release-footer.md` — don't paste it into the
draft.

## Documentation

`docs/` is written for a user, not for a maintainer. Prose over bullet lists,
British spelling, no marketing register. `README.md` carries the warning box and
the `## Legal` section; both are deliberate and should not be trimmed without
asking.

The integration talks to the Livoltek **portal**. Describe it that way
everywhere, in code comments and user-facing strings included.
