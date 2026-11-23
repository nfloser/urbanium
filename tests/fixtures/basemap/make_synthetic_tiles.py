"""Tiny synthetic PMTiles basemap in the Protomaps schema, for local rendering tests only."""

import gzip
import math
import sys

from mapbox_vector_tile import encode
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

south, west, north, east = 52.30, 13.05, 52.70, 13.80


def merc(lon, lat):
    x = lon * 20037508.34 / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) * 20037508.34 / math.pi
    return x, y


def tile_bounds(z, x, y):
    n = 2**z
    lon0 = x / n * 360 - 180
    lon1 = (x + 1) / n * 360 - 180
    lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return merc(lon0, lat0) + merc(lon1, lat1)


def tiles(z):
    n = 2**z
    x0 = int((west + 180) / 360 * n)
    x1 = int((east + 180) / 360 * n)

    def ty(lat):
        return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    for x in range(x0, x1 + 1):
        for y in range(ty(north), ty(south) + 1):
            yield x, y


def ring(points):
    return "POLYGON((" + ",".join(f"{a} {b}" for a, b in points + [points[0]]) + "))"


def line(points):
    return "LINESTRING(" + ",".join(f"{a} {b}" for a, b in points) + ")"


land = [merc(12.5, 52.0), merc(14.5, 52.0), merc(14.5, 53.0), merc(12.5, 53.0)]
river = [
    merc(lo, la)
    for lo, la in [
        (13.05, 52.53),
        (13.21, 52.54),
        (13.29, 52.53),
        (13.41, 52.515),
        (13.50, 52.48),
        (13.58, 52.43),
        (13.70, 52.37),
        (13.80, 52.36),
    ]
]
river_poly = [(x, y + 120) for x, y in river] + [(x, y - 120) for x, y in reversed(river)]
lake = [merc(13.17, 52.43), merc(13.22, 52.43), merc(13.22, 52.47), merc(13.17, 52.47)]
roads = [
    [merc(13.08, 52.5), merc(13.76, 52.5)],
    [merc(13.4, 52.34), merc(13.4, 52.67)],
    [merc(13.15, 52.62), merc(13.7, 52.38)],
]
with open(sys.argv[1], "wb") as f:
    w = Writer(f)
    for z in range(0, 13):
        for x, y in tiles(z):
            b = tile_bounds(z, x, y)
            layers = [
                {
                    "name": "earth",
                    "features": [{"geometry": ring(land), "properties": {"kind": "earth"}}],
                },
                {
                    "name": "water",
                    "features": [
                        {"geometry": ring(river_poly), "properties": {"kind": "water"}},
                        {"geometry": ring(lake), "properties": {"kind": "lake"}},
                    ],
                },
                {
                    "name": "roads",
                    "features": [
                        {
                            "geometry": line(r),
                            "properties": {"kind": "major_road", "kind_detail": "primary"},
                        }
                        for r in roads
                    ],
                },
            ]
            data = encode(layers, default_options={"quantize_bounds": b, "extents": 4096})
            w.write_tile(zxy_to_tileid(z, x, y), gzip.compress(data))
    w.finalize(
        {
            "tile_type": TileType.MVT,
            "tile_compression": Compression.GZIP,
            "min_zoom": 0,
            "max_zoom": 12,
            "min_lon_e7": int(west * 1e7),
            "min_lat_e7": int(south * 1e7),
            "max_lon_e7": int(east * 1e7),
            "max_lat_e7": int(north * 1e7),
            "center_zoom": 10,
            "center_lon_e7": int(13.4 * 1e7),
            "center_lat_e7": int(52.5 * 1e7),
        },
        {"attribution": "synthetic test tiles", "vector_layers": []},
    )
