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


def test_browser_comparison_filters_cities_and_sources() -> None:
    """Exercise the browser's actual comparison function without external services."""
    import shutil

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser behavior regression check")

    root = Path(__file__).resolve().parents[1]
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  document: { querySelector: () => ({}) },
  fetch: () => Promise.reject(new Error("offline test fixture")),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

const cities = [
  {
    id: "berlin", name: "Berlin",
    capabilities: [{id: "weather", support: "configured"}],
    sources: [
      {provider: "dwd", capabilities: ["weather"]},
      {provider: "vbb", capabilities: ["realtime_transport"]},
    ],
  },
  {
    id: "mainz", name: "Mainz",
    capabilities: [{id: "weather", support: "candidate"}],
    sources: [{provider: "other", capabilities: ["weather"]}],
  },
];
const compare = (selected, capability) => JSON.parse(JSON.stringify(
  vm.runInContext("compare", context)(cities, new Set(selected), capability),
));

assert.deepStrictEqual(compare(["berlin"], "weather"), [{
  city_id: "berlin", city_name: "Berlin",
  capability: {id: "weather", support: "configured"},
  sources: [{provider: "dwd", capabilities: ["weather"]}],
}]);
assert.deepStrictEqual(compare(["mainz"], "realtime_transport"), [{
  city_id: "mainz", city_name: "Mainz", capability: null, sources: [],
}]);
assert.deepStrictEqual(compare([], "weather"), []);
"""
    subprocess.run(
        [node, "-e", script, str(root / "demo" / "explorer.js")],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )



def test_browser_demo_reports_catalog_load_failure() -> None:
    """A failed catalog request must produce an explicit user-facing error."""
    import shutil

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser behavior regression check")

    root = Path(__file__).resolve().parents[1]
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const nodes = new Map();
const context = {
  document: {
    querySelector: (selector) => {
      if (!nodes.has(selector)) nodes.set(selector, {});
      return nodes.get(selector);
    },
  },
  fetch: () => Promise.reject(new Error("offline test fixture")),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

setImmediate(() => {
  assert.equal(
    nodes.get("#status").textContent,
    "Der Stadtkatalog konnte nicht geladen werden. Bitte lade die Seite neu.",
  );
});
"""
    subprocess.run(
        [node, "-e", script, str(root / "demo" / "explorer.js")],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
