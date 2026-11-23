# Twin Explorer

A static client for Urbanium twin snapshots (`urbanium.twin-snapshot/1`). It runs on GitHub Pages without a backend: a scheduled workflow builds fresh snapshots from live sources twice an hour and publishes them next to the explorer.

## What it shows

- **Karte**: every discovered weather station and gauge in the city's search area, with its latest value printed on the map like a synoptic chart. Hover for time, freshness and source; select for details. Stale values are dashed, stations without values stay visible but empty.
- **Erkenntnisse**: agent results in plain language (temperature difference across stations at one shared time, six-hour gauge trends), each with "Wie berechnet?" showing rule, inputs and run time. Unanswerable questions say why.
- **Detail**: value, recent series, derived context, relationships, attributes and provenance (source, licence, record checksum, retrieval time).
- **Wissensgraph**: stations, gauges, water bodies and the search area with every relationship; blue edges come from the source, ochre dashed edges are derived. The Turtle export of the same graph is one click away.
- **Städte**: declared capabilities, live coverage and answerable analyses per city, plus the configuration that added Köln and Hamburg without code.

## Run locally

~~~bash
pip install -e ".[dev]"
urbanium-twin build --out demo/explorer/data          # live sources
python -m http.server --directory demo/explorer 8000
~~~

Offline, use invented example data (clearly labelled in the UI as not real):

~~~bash
python demo/sample_recording.py /tmp/urbanium-sample
urbanium-twin build --replay /tmp/urbanium-sample --out demo/explorer/data
~~~

`demo/explorer/data/` is build output and is not committed.

## Design notes

- The map reads like an authority's measurement chart rather than a dashboard: cool survey-paper background, ink-navy type, water blue for gauges and a fixed diverging temperature scale (−10 to 30 °C) so cities stay comparable.
- Ochre is reserved for derived knowledge: agent results, derived relationships and the context they add. Anything ochre was computed, not measured.
- Typeface: Barlow and Barlow Semi Condensed (SIL OFL), self-hosted together with Leaflet (BSD-2-Clause). Only basemap tiles (© OpenStreetMap contributors, © CARTO) load from a third party.
- Upstream text is only ever inserted as text, never as HTML.

## Checks

`tests/test_twin_explorer_contract.py` keeps the explorer's schema versions in step with Python and verifies local assets. `tests/e2e/test_explorer_browser.py` renders the explorer against synthetic data in Chrome; it runs when Playwright and Chrome/Chromium are available (as on GitHub's Ubuntu runners).
