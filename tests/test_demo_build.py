"""Regression checks for the generated, static city-comparison demo."""

import json
import subprocess
import sys
from pathlib import Path

from urbanium.registry import CityRegistry


def test_browser_demo_bundle_matches_canonical_registry(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "published-demo"

    subprocess.run(
        [sys.executable, str(root / "demo" / "build.py"), str(output)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert {path.name for path in output.iterdir()} == {
        "index.html",
        "explorer.js",
        "catalog.json",
    }
    assert (output / "index.html").read_bytes() == (root / "demo" / "index.html").read_bytes()
    assert (output / "explorer.js").read_bytes() == (root / "demo" / "explorer.js").read_bytes()

    catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    expected = [
        city.model_dump(mode="json") for city in CityRegistry.from_directory(root / "cities").cities
    ]
    assert catalog == expected
    assert catalog, "The published demo must contain at least one configured city"
