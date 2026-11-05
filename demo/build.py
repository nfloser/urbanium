"""Build the static browser demo from the canonical city registry."""

import argparse
from html import escape
from pathlib import Path

from urbanium.registry import CityRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    cities = CityRegistry.from_directory(Path("cities")).cities
    sections = []
    for city in cities:
        capabilities = "".join(
            f"<li>{escape(item.id)} — {escape(item.support.value)}</li>"
            for item in city.capabilities
        )
        sources = "".join(
            f"<li>{escape(source.provider)} — {escape(source.status.value)} "
            f"({escape(', '.join(source.capabilities))})</li>"
            for source in city.sources
        )
        sections.append(
            f"<details><summary>{escape(city.name)}</summary>"
            f"<h3>Capabilities</h3><ul>{capabilities}</ul>"
            f"<h3>Data sources</h3><ul>{sources}</ul></details>"
        )

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "index.html").write_text(
        """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Urbanium demo</title>
<style>
  :root { color-scheme: light dark; font: 1rem/1.6 system-ui, sans-serif; }
  main { max-width: 45rem; margin: 3rem auto; padding: 0 1rem; }
  details { border: 1px solid GrayText; border-radius: .5rem; margin: 1rem 0; padding: 1rem; }
  summary { cursor: pointer; font-weight: 650; }
</style>
<main>
<h1>Urbanium demo</h1>
<p>This catalog snapshot comes from the city definitions in the published build.
Expand a city to see its capabilities and declared sources.
Status describes the configuration. Live readings require the Urbanium API.</p>
"""
        + "\n".join(sections)
        + '<p><a href="https://github.com/nfloser/urbanium">Source repository</a></p></main>\n',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
