"""The static explorer stays in step with the snapshot contract it renders."""

import re
from pathlib import Path

from urbanium.twin.snapshot import INDEX_SCHEMA, SNAPSHOT_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
EXPLORER = ROOT / "demo" / "explorer"


def test_explorer_expects_the_current_schema_versions() -> None:
    script = (EXPLORER / "app.js").read_text(encoding="utf-8")

    assert f'const SNAPSHOT_SCHEMA = "{SNAPSHOT_SCHEMA}";' in script
    assert f'const INDEX_SCHEMA = "{INDEX_SCHEMA}";' in script


def test_every_local_asset_referenced_by_the_explorer_exists() -> None:
    html = (EXPLORER / "index.html").read_text(encoding="utf-8")
    css = (EXPLORER / "styles.css").read_text(encoding="utf-8")
    references = re.findall(r'(?:src|href)="([^"#:]+)"', html) + re.findall(
        r'url\("([^"]+)"\)', css
    )

    assert references
    missing = [ref for ref in references if ref != "./" and not (EXPLORER / ref).is_file()]
    assert not missing


def test_explorer_never_injects_upstream_text_as_html() -> None:
    script = (EXPLORER / "app.js").read_text(encoding="utf-8")

    assert "innerHTML" not in script
    # The marker icon is the only HTML string; every upstream value is escaped.
    body = script[script.index("function markerIcon(") : script.index("function tooltip(")]
    assert ".label" not in body
    for escaped in ("esc(names[i])", "esc(value)", "esc(e.id)", "esc(QUANTITY"):
        assert escaped in body, escaped


def test_vendored_third_party_code_keeps_its_licences() -> None:
    assert (EXPLORER / "vendor" / "leaflet" / "LICENSE").is_file()
    assert (EXPLORER / "vendor" / "fonts" / "OFL.txt").is_file()
    assert (EXPLORER / "vendor" / "protomaps-leaflet" / "LICENSE").is_file()


def test_explorer_does_not_shadow_browser_globals() -> None:
    script = (EXPLORER / "app.js").read_text(encoding="utf-8")
    declared = set(re.findall(r"^(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)", script, re.M))
    browser_globals = {
        "history",
        "location",
        "name",
        "status",
        "open",
        "close",
        "print",
        "event",
        "top",
        "parent",
        "self",
        "length",
        "origin",
        "screen",
        "navigator",
        "document",
    }

    assert not declared & browser_globals
