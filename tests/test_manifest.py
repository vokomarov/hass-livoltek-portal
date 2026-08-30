"""The manifest must stay consistent with the domain and the dependency ban."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.livoltek_portal.const import DOMAIN

COMPONENT_DIR = Path("custom_components/livoltek_portal")


def test_manifest_domain_matches_directory_and_const() -> None:
    manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text())
    assert manifest["domain"] == DOMAIN
    assert COMPONENT_DIR.name == DOMAIN


def test_manifest_declares_no_requirements() -> None:
    manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text())
    assert manifest["requirements"] == []


def test_manifest_is_cloud_polling_with_config_flow() -> None:
    manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text())
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["config_flow"] is True
