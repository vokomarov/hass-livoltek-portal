"""Metadata that HACS, hassfest, and users depend on."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = json.loads(
    (ROOT / "custom_components" / "livoltek_portal" / "manifest.json").read_text()
)
HACS = json.loads((ROOT / "hacs.json").read_text())
README = (ROOT / "README.md").read_text()
RELEASE_WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text()
RELEASE_FOOTER = (ROOT / ".github" / "release-footer.md").read_text()


def test_the_manifest_is_complete() -> None:
    assert MANIFEST["domain"] == "livoltek_portal"
    assert MANIFEST["config_flow"] is True
    assert MANIFEST["iot_class"] == "cloud_polling"
    assert MANIFEST["integration_type"] == "hub"
    # No PyPI dependency: the client is vendored in api/ precisely so a HACS
    # install never has to resolve a package at runtime.
    assert MANIFEST["requirements"] == []
    for field in ("documentation", "issue_tracker", "codeowners", "version"):
        assert MANIFEST.get(field), f"manifest is missing {field}"
    assert MANIFEST["documentation"].startswith("https://")


def test_hacs_metadata_points_at_the_right_directory() -> None:
    assert HACS["name"]
    assert HACS["homeassistant"] == "2025.2.0"
    assert HACS.get("render_readme") is True


def test_hacs_installs_the_archive_the_release_workflow_actually_builds() -> None:
    """`zip_release` makes HACS download `filename` from the release instead of
    the repository tree. A rename on either side leaves every install failing
    with a 404, and nothing else in the repo connects the two names."""
    assert HACS.get("zip_release") is True
    assert HACS["filename"] in RELEASE_WORKFLOW
    # The manual-install instructions name the same asset users download.
    assert HACS["filename"] in RELEASE_FOOTER


def test_the_release_footer_is_appended_at_most_once() -> None:
    """The workflow skips the append when it finds this marker in the notes.
    A marker that only exists on one side means the footer is re-appended
    every time the release is republished."""
    marker = "<!-- release-footer -->"
    assert marker in RELEASE_FOOTER
    assert marker in RELEASE_WORKFLOW


def test_every_github_reference_names_the_same_repository() -> None:
    """The owner and repo name are written into badges, the HACS install link,
    the manifest, and the release body. A rename that misses one leaves a link
    that 404s for users but for nobody who reviews the diff."""
    repo = MANIFEST["documentation"].removeprefix("https://github.com/")
    owner, name = repo.split("/")
    # Other people's repositories, linked on purpose. Anything not listed here
    # is a link that a rename left behind.
    external = {"adamlonsdale/hass-livoltek"}
    for path in (
        "README.md",
        "docs/installation.md",
        "docs/troubleshooting.md",
        "docs/entities.md",
        ".github/release-footer.md",
    ):
        text = (ROOT / path).read_text()
        for link in re.findall(r"https://github\.com/([\w.-]+/[\w.-]+)", text):
            if link in external:
                continue
            assert link == repo, f"{path} points at {link}, not {repo}"
        for badge in re.findall(r"owner=([\w.-]+)&repository=([\w.-]+)", text):
            assert badge == (owner, name), f"{path} HACS link points at {badge}"


def test_the_readme_states_the_credential_risk_plainly() -> None:
    """A user cannot consent to a risk that is not written down."""
    lowered = README.lower()
    assert "md5" in lowered
    assert "password-equivalent" in lowered
    assert ".storage" in README


def test_the_docs_document_the_energy_dashboard_mapping() -> None:
    """The mapping moved out of the README, but a user still has to be able to
    find it -- so both the table and the README's pointer to it are checked."""
    entities = (ROOT / "docs" / "entities.md").read_text()
    for entity in (
        "grid_imported_total",
        "grid_exported_total",
        "pv_energy_total",
        "battery_charged_total",
        "battery_discharged_total",
    ):
        assert entity in entities, f"{entity} is missing from docs/entities.md"
    assert "docs/entities.md#energy-dashboard" in README


def test_the_readme_never_claims_an_official_relationship() -> None:
    assert "not affiliated" in README.lower()
