# Synthetic basemap fixture

`berlin.pmtiles` is a tiny invented vector basemap in the Protomaps schema
(one land polygon, a river, a lake and three roads around Berlin), made with
`make_synthetic_tiles.py` (needs `pmtiles` and `mapbox-vector-tile`, which are
not project dependencies). It only proves that the explorer renders a
self-hosted PMTiles file; it is not map data.
