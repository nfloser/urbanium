# Live checks

Deterministic CI never talks to upstream sources. Their health and formats are checked separately:

- **Every Pages build** (push and twice an hour) builds snapshots from live sources. Outages show up in the snapshot and, thanks to [last known values](../concepts/twin-snapshot.md#last-known-values), do not blank the published site.
- **Weekly live check** (`.github/workflows/live-check.yml`, Mondays and on demand) runs the opt-in live tests against DWD, PEGELONLINE and VBB, records every upstream response with `urbanium-twin build --record` and keeps the recording as the `live-recording` artifact for 30 days. When a test fails it opens an issue with a link to the run.

Run the live tests locally:

~~~bash
URBANIUM_LIVE_AREA=1 URBANIUM_LIVE_DWD=1 URBANIUM_LIVE_DWD_STATIONS=1 URBANIUM_LIVE_VBB=1 pytest -m live tests/live
~~~

A recording from the artifact can be replayed offline with `urbanium-twin build --replay <dir>`. When a format changes, add the relevant recorded response as a fixture before adapting the parser, so the change is covered by deterministic tests.
