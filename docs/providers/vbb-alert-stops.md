# VBB stops named in alerts

`urbanium.providers.vbb.alert_stops` turns the stop ids that current VBB GTFS-Realtime alerts name into a map layer for Berlin.

- Realtime: `https://production.gtfsrt.vbb.de/data` (CC BY 4.0), read through the existing `VbbGtfsRtProvider`.
- Static: the stop-level ("mastscharf") GTFS archive from VBB (CC BY 4.0, updated weekly), used only to locate stop ids and name them.

## What an entity means

A `transport_stop` entity is a stop that at least one current alert selector names. A selector can also restrict a route or a trip, so **named is not affected**: the explorer says "in Störungsmeldung genannt" and states this in tooltip and detail. Attributes carry the stop id, the number and ids of alerts naming it, and the German header text of the first alert.

## Binding

`cities/berlin/providers/vbb_alert_stops.yaml` names the realtime source, the static source, both URLs, the static archive's maximum age (default 7 days) and the feed freshness.

## Behaviour

1. Read the realtime feed once (alert stop references and alert header texts).
2. Load the static archive, from the build cache (`--cache`) when it is younger than `static_max_age_days`, otherwise downloaded and cached with its real retrieval time.
3. Resolve each named stop id exactly in `stops.txt`. Ids the inventory does not contain are counted, not guessed; the read is then degraded with "n of m alert stop ids are not in the static GTFS inventory". This is the running check that realtime and static ids still share a namespace.
4. Keep resolved stops inside the city's search envelope.

The read always contains one network observation (`named_stops_in_area`), so a moment without named stops is a valid, available answer. Per stop it reports `alert_mentions`.

The static archive (~80 MB) is cached per calendar week in the Pages workflow.
