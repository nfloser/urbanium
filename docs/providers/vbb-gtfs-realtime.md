# VBB GTFS-Realtime operational alert adapter

Urbanium's Berlin reference deployment uses the official Verkehrsverbund Berlin-Brandenburg (VBB) GTFS-Realtime feed as the first implemented realtime mobility source.

- Upstream dataset page: https://unternehmen.vbb.de/digitale-services/datensaetze/
- Production feed data: https://production.gtfsrt.vbb.de/data
- Urbanium capability: `realtime_transport`
- Urbanium source: `vbb_gtfs_rt`

The city registry records the source under the VBB's published CC BY 4.0 terms. Upstream attribution and licensing remain authoritative.

The host root (`https://production.gtfsrt.vbb.de/`) is an informational
HTML page, **not** the protobuf feed. The Berlin provider binding and city
registry both point to `/data`, which the feed operator identifies as the
actual GTFS-Realtime resource. The adapter does not discover or append this
path automatically. The opt-in live smoke test uses the configured data URL;
deterministic CI does not request it.

Invalid UTF-8 in the city provider YAML is reported as a VBB configuration
error with the affected file path, just like unreadable files or malformed YAML.
It is not treated as an unavailable live feed or replaced with default settings.

## Normalized observation

The adapter parses one GTFS-Realtime `FeedMessage` and emits one canonical numeric observation:

- entity: `transport_network:vbb_network`
- quantity: `active_service_alerts`
- value: count of feed entities carrying the GTFS-Realtime `Alert` message
- unit: `1`
- capability: `realtime_transport`

A count of zero is a valid available observation. It means the parsed snapshot contains no Alert entities; it does **not** mean that the entire transport network is disruption-free.

Trip updates and vehicle positions may coexist in the feed but are not reinterpreted as alerts. The adapter does not infer affected routes, disruption severity or causes.

## Explicit Alert stop references

For consumers that need to inspect source-backed identifiers, call
`VbbGtfsRtProvider.read_snapshot()`. It performs **one** feed request and
returns a `VbbAlertSnapshot` containing the unchanged canonical
`ProviderResult` and a tuple of `VbbAlertStopReference` values.
The original `read()` API still returns only the canonical provider result.

A stop reference contains the raw GTFS-Realtime Alert entity ID, its
zero-based `informed_entity` selector index, and the selector's explicit
`stop_id`. Order and repeated references are retained. The selector
index identifies its position in the source feed; the snapshot does **not**
retain the full selector or its additional route/trip qualifications.
Selectors without a nonempty `stop_id` and non-Alert feed entities produce
no stop reference. Invalid or unavailable feeds return an empty tuple; a
valid feed with a missing header timestamp retains the references while
reporting degraded temporal provenance as before.

**These are identifiers, not locations or impact assertions.** A selector
may constrain a route or trip in addition to a stop. This extraction does
not interpret those qualifications, resolve stop IDs to coordinates, claim
that a stop is disrupted, or infer an affected service area. A versioned,
licensed GTFS static stop inventory and an explicit selector interpretation
would be needed before considering spatial joins with DWD station points.
An empty tuple does not mean that no service alerts exist: alerts may
target routes, trips or agencies without naming a stop.

The optional [offline GTFS static stop lookup](vbb-static-stop-points.md)
can resolve **exact** referenced IDs to source-backed points when a
consumer supplies a licensed, version-compatible `stops.txt` inventory.
It does not interpret route/trip qualifications or turn a match into an
impact claim.

## Optional realtime feed version

`VbbAlertSnapshot.feed_version` retains the optional GTFS-Realtime
`FeedHeader.feed_version` label from the **same** successful feed read.
Missing, blank and nonprinting labels yield `None`; a rejected optional
label does not invalidate the alert count or explicit stop references.
A valid label is also retained when the feed timestamp is missing and the
provider result is degraded. Unavailable snapshots have no version.

This is an unverified publisher-provided string, not a verified release
identity or a guarantee that the Alert stop IDs match a supplied GTFS
static archive. The separate static inventory exposes its own optional
`feed_version` from `feed_info.txt`; Urbanium does **not** automatically
compare these labels or infer compatibility from matching strings.
Callers must verify publisher, namespace and applicable dataset versions
before resolving realtime stop IDs against static data.

## Time and freshness

When the optional GTFS-Realtime feed-header timestamp is present, it becomes `observed_at`. Freshness is assessed against the configured threshold, currently five minutes.

When the feed omits that optional timestamp, the alert count is still usable but has weaker temporal provenance. Urbanium then:

- uses the receipt timestamp as the snapshot time;
- marks the observation quality as `receipt_fallback`;
- reports the provider result as `degraded`;
- reports freshness as `unknown`.

The receipt timestamp is captured after the feed has been downloaded, not when the request begins. A feed timestamp later than that actual receipt time is rejected rather than silently rewritten. This avoids falsely rejecting a feed created while the HTTP request was in progress.

## Failure behavior

The adapter requests gzip and identifies itself as Urbanium. Both the downloaded
body and the decoded protobuf are limited to 10 MB.

Timeouts, upstream I/O errors, malformed protobuf messages and feeds above the configured size boundary return explicit unavailable `ProviderResult` values. No cached value or fabricated alert count is substituted.

## Cross-domain boundary

This adapter is intended to support the first Urbanium cross-domain demonstrator together with the existing DWD weather slice.

The demonstrator may show weather and transport operational signals in the same derived context. It must not claim that weather caused a VBB alert unless a future evidence-backed relationship supports that claim.

## Tests

Deterministic tests construct GTFS-Realtime protobuf messages in memory; normal CI performs no VBB network access.

An optional smoke test can be enabled explicitly:

    URBANIUM_LIVE_VBB=1 pytest -m live tests/live/test_vbb_gtfs_rt_live.py

The opt-in check reads one complete `VbbAlertSnapshot` from the configured
endpoint and checks the canonical nonnegative Alert count plus structural
invariants of any explicit stop references and optional version label. It
does not require the live feed to contain alerts, stop references or a
version label. Passing this check establishes only that one current
response was readable; it does not verify static GTFS compatibility,
coverage, upstream reliability or transport impacts. Normal CI skips it.

## Berlin dashboard

The observation API exposes separate counts of alert, trip-update and vehicle-position
entries from one snapshot. These are feed entity counts, with the snapshot timestamp
and freshness shared across them. Zero means the feed contained no entries of that
type. It does not establish network-wide coverage or an absence of incidents.

The dashboard also displays DWD temperatures. Static VBB stops, DWD station locations,
alert stop references and the weather/transport readiness analysis are available in
code but are not yet wired into the dashboard.
