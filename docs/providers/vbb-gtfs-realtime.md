# VBB GTFS-Realtime operational alert adapter

Urbanium's Berlin reference deployment uses the official Verkehrsverbund Berlin-Brandenburg (VBB) GTFS-Realtime feed as the first implemented realtime mobility source.

- Upstream dataset page: https://unternehmen.vbb.de/digitale-services/datensaetze/
- Production feed: https://production.gtfsrt.vbb.de
- Urbanium capability: `realtime_transport`
- Urbanium source: `vbb_gtfs_rt`

The city registry records the source under the VBB's published CC BY 4.0 terms. Upstream attribution and licensing remain authoritative.

## Normalized observation

The adapter parses one GTFS-Realtime `FeedMessage` and emits one canonical numeric observation:

- entity: `transport_network:vbb_network`
- quantity: `active_service_alerts`
- value: count of feed entities carrying the GTFS-Realtime `Alert` message
- unit: `1`
- capability: `realtime_transport`

A count of zero is a valid available observation. It means the parsed snapshot contains no Alert entities; it does **not** mean that the entire transport network is disruption-free.

Trip updates and vehicle positions may coexist in the feed but are not reinterpreted as alerts. The adapter does not infer affected routes, disruption severity or causes.

## Time and freshness

When the optional GTFS-Realtime feed-header timestamp is present, it becomes `observed_at`. Freshness is assessed against the configured threshold, currently five minutes.

When the feed omits that optional timestamp, the alert count is still usable but has weaker temporal provenance. Urbanium then:

- uses the receipt timestamp as the snapshot time;
- marks the observation quality as `receipt_fallback`;
- reports the provider result as `degraded`;
- reports freshness as `unknown`.

A feed timestamp later than the receipt time is rejected rather than silently rewritten.

## Failure behavior

Timeouts, upstream I/O errors, malformed protobuf messages and feeds above the configured size boundary return explicit unavailable `ProviderResult` values. No cached value or fabricated alert count is substituted.

## Cross-domain boundary

This adapter is intended to support the first Urbanium cross-domain demonstrator together with the existing DWD weather slice.

The demonstrator may show weather and transport operational signals in the same derived context. It must not claim that weather caused a VBB alert unless a future evidence-backed relationship supports that claim.

## Tests

Deterministic tests construct GTFS-Realtime protobuf messages in memory; normal CI performs no VBB network access.

An optional smoke test can be enabled explicitly:

    URBANIUM_LIVE_VBB=1 pytest -m live tests/live/test_vbb_gtfs_rt_live.py
