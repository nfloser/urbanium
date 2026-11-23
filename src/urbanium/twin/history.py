"""Append-only observation archive and daily summaries for twin snapshots.

The archive keeps one value per entity and full hour, in monthly CSV files
per city (`<root>/<city>/<YYYY-MM>.csv`). It is written by the build and
stored on the repository's `data` branch, so trends can reach beyond what the
sources themselves keep (one day at DWD `now`, 31 days at PEGELONLINE).
"""

import csv
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from urbanium.twin.snapshot import DailyStat, TwinSnapshot

COLUMNS = ("entity", "quantity", "observed_at", "value", "unit")
WINDOW_DAYS = 30


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_history(root: Path, twin: TwinSnapshot) -> int:
    """Add this snapshot's full-hour values; returns the number of new rows.

    Carried-over (last known) values were archived when they were measured and
    are skipped here.
    """

    rows: dict[str, list[tuple[str, str, str, str, str]]] = defaultdict(list)
    for entity in twin.entities:
        if entity.carried_over_from is not None or entity.latest is None:
            continue
        for moment, value in entity.series:
            if moment.astimezone(UTC).minute != 0 or moment.second != 0:
                continue
            month = moment.astimezone(UTC).strftime("%Y-%m")
            rows[month].append(
                (entity.id, entity.latest.quantity_id, _iso(moment), value, entity.latest.unit)
            )

    added = 0
    directory = root / twin.city.id
    directory.mkdir(parents=True, exist_ok=True)
    for month, new_rows in sorted(rows.items()):
        path = directory / f"{month}.csv"
        known: set[tuple[str, str]] = set()
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as handle:
                known = {(row["entity"], row["observed_at"]) for row in csv.DictReader(handle)}
        fresh = [row for row in new_rows if (row[0], row[2]) not in known]
        if not fresh:
            continue
        write_header = not path.is_file()
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            if write_header:
                writer.writerow(COLUMNS)
            writer.writerows(sorted(set(fresh)))
        added += len(set(fresh))
    return added


def daily_stats(
    root: Path, twin: TwinSnapshot, *, days: int = WINDOW_DAYS
) -> dict[str, list[DailyStat]]:
    """Per entity: min, max and mean per local day over the last `days` days."""

    zone = ZoneInfo(twin.city.timezone)
    last_day = twin.generated_at.astimezone(zone).date()
    first_day = last_day - timedelta(days=days - 1)
    directory = root / twin.city.id
    if not directory.is_dir():
        return {}

    values: dict[str, dict[date, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple[str, str]] = set()
    for path in sorted(directory.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row["entity"], row["observed_at"])
                if key in seen:
                    continue
                seen.add(key)
                moment = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
                local_day = moment.astimezone(zone).date()
                if first_day <= local_day <= last_day:
                    values[row["entity"]][local_day].append(Decimal(row["value"]))

    result: dict[str, list[DailyStat]] = {}
    for entity, per_day in values.items():
        result[entity] = [
            DailyStat(
                day=day,
                min=str(min(items)),
                max=str(max(items)),
                mean=str(
                    (sum(items, Decimal(0)) / len(items)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                ),
                count=len(items),
            )
            for day, items in sorted(per_day.items())
        ]
    return result


def attach_history(twin: TwinSnapshot, stats: dict[str, list[DailyStat]]) -> TwinSnapshot:
    return twin.model_copy(
        update={
            "entities": [
                entity.model_copy(update={"daily": stats.get(entity.id, [])})
                for entity in twin.entities
            ]
        }
    )
