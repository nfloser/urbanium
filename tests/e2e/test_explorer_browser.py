"""Render the explorer in a real browser against a synthetic snapshot.

Skipped unless Playwright and a Chromium/Chrome binary are available
(`URBANIUM_E2E_CHROME` may point at the browser executable).
"""

import functools
import http.server
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
CHROME = (
    os.environ.get("URBANIUM_E2E_CHROME")
    or shutil.which("google-chrome")
    or shutil.which("chromium")
)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(CHROME is None, reason="no Chrome/Chromium for e2e test"),
]


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    root = tmp_path_factory.mktemp("site")
    recording = tmp_path_factory.mktemp("recording")
    shutil.copytree(ROOT / "demo" / "explorer", root, dirs_exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    subprocess.run(
        [sys.executable, str(ROOT / "demo" / "sample_recording.py"), str(recording)],
        check=True,
        cwd=ROOT,
        env=env,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "urbanium.twin",
            "build",
            "--replay",
            str(recording),
            "--out",
            str(root / "data"),
        ],
        check=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def test_map_insights_detail_graph_and_compare_render(site: str) -> None:
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Map tiles are external and irrelevant here.
        page.route("**/basemaps.cartocdn.com/**", lambda route: route.abort())
        page.goto(site + "?city=berlin")

        page.wait_for_selector(".mk")
        assert "Beispieldaten" in page.inner_text("#notice")
        # Every entity is reachable on the map, even where nearby gauges share a label.
        assert page.locator(".mk-temp [data-entity]").count() == 6
        assert page.locator(".mk-gauge [data-entity]").count() == 19
        assert page.locator(".mk-gauge").count() < 19  # lock pairs are grouped
        assert "Temperaturunterschied" in page.inner_text("#insights")

        page.locator(".leaflet-marker-icon").first.focus()
        page.keyboard.press("Enter")
        assert page.locator("#detail h2").inner_text()
        assert "Herkunft" in page.inner_text("#detail")
        assert page.evaluate("document.activeElement.classList.contains('mk-host')")
        assert page.locator(".mk.selected").count() == 1
        overlapping = page.evaluate(
            """() => {
              const r = [...document.querySelectorAll('.mk:not(.muted)')]
                .map((e) => e.getBoundingClientRect());
              let n = 0;
              for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) {
                const a = r[i], b = r[j];
                const x = a.left < b.right && a.right > b.left;
                if (x && a.top < b.bottom && a.bottom > b.top) n++;
              }
              return n;
            }"""
        )
        assert overlapping == 0

        page.click("button[data-view=graph]")
        assert page.locator("#graph .node").count() >= 10

        page.click("button[data-view=compare]")
        page.wait_for_selector(".matrix")
        assert "Köln" in page.inner_text(".matrix")

        page.click("#cities button[data-city=mainz]")
        page.click("button[data-view=map]")
        page.wait_for_selector(".insight.unanswered")
        assert "mindestens drei" in page.inner_text("#insights")

        assert not errors
        browser.close()
