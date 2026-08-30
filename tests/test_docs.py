"""`docs/entities.md` is a hand-written table over a generated list.

Nothing in Home Assistant fails when the two disagree, which is exactly why the
check has to live here: a sensor added without a doc row is invisible to users,
and a doc row left behind after a sensor is renamed sends them looking for an
entity that does not exist.
"""

from __future__ import annotations

import re
from pathlib import Path

from custom_components.livoltek_portal.binary_sensor import ONLINE
from custom_components.livoltek_portal.sensor import SENSOR_DESCRIPTIONS

_ROOT = Path(__file__).parent.parent
_ENTITIES_DOC = _ROOT / "docs" / "entities.md"

# Markdown inline links, minus anything with a scheme (`https:`, `mailto:`) and
# minus pure anchors (`#section`), which point within their own page.
_LINK = re.compile(r"\]\((?!\w+:)(?!#)([^)\s]+)\)")

# A leading `|` and a trailing `|` -- the first cell of a table row, which is
# where every key lives. Prose mentions like `sensor.<device>_battery_soc` and
# the Energy dashboard rows are deliberately not matched.
_TABLE_KEY = re.compile(r"^\| `([a-z0-9_]+)` \|", re.MULTILINE)


def test_the_entity_table_lists_every_entity_and_no_others() -> None:
    documented = set(_TABLE_KEY.findall(_ENTITIES_DOC.read_text()))
    actual = {d.key for d in SENSOR_DESCRIPTIONS} | {ONLINE.key}
    assert documented - actual == set(), "documented but does not exist"
    assert actual - documented == set(), "exists but is not documented"


def test_every_relative_link_in_the_docs_resolves() -> None:
    """A dead link in documentation fails silently -- GitHub renders it, and
    the reader only finds out by clicking."""
    pages = [*sorted(_ROOT.glob("*.md")), *sorted(_ROOT.glob("docs/**/*.md"))]
    broken = [
        f"{page.relative_to(_ROOT)} -> {target}"
        for page in pages
        for target in _LINK.findall(page.read_text())
        if not (page.parent / target.split("#", 1)[0]).exists()
    ]
    assert broken == []


def test_the_counts_in_the_prose_match_the_table() -> None:
    """The header sentence is the first thing a reader trusts and the last
    thing anyone remembers to update."""
    text = _ENTITIES_DOC.read_text()
    enabled = sum(d.entity_registry_enabled_default for d in SENSOR_DESCRIPTIONS)
    disabled = len(SENSOR_DESCRIPTIONS) - enabled
    assert f"**{enabled} sensors enabled by" in text
    assert f"**{disabled} diagnostic sensors**" in text
