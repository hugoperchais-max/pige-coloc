"""Outil ONE-SHOT : transforme le GTFS CTS en un fichier compact `cts_transit.json`.

À relancer seulement si le réseau change (nouvelle ligne, arrêts déplacés) —
sinon jamais. Le bot, lui, ne lit que le JSON produit (léger, embarqué au repo).

Produit une liste de "stations" (arrêts regroupés par nom, quais fusionnés) :
    {"name", "lat", "lon", "lines": [...], "tram": bool}

Usage : py -3.12 build_transit.py            # télécharge le GTFS et régénère
        py -3.12 build_transit.py gtfs.zip   # depuis un zip déjà téléchargé
"""
import csv
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import httpclient

GTFS_URL = "https://opendata.cts-strasbourg.eu/google_transit.zip"
OUT = Path(__file__).parent / "cts_transit.json"


def _read(zf: zipfile.ZipFile, name: str):
    with zf.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def build(zip_bytes: bytes) -> list[dict]:
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    # 1. route_id -> (nom court, est-ce du tram ?)
    routes = {}
    for r in _read(zf, "routes.txt"):
        routes[r["route_id"]] = (r.get("route_short_name") or r.get("route_long_name", ""),
                                 r.get("route_type") == "0")  # 0 = tram

    # 2. On garde 1 trip par (route, direction) : suffit pour savoir QUELLES
    #    lignes desservent QUELS arrêts (inutile de lire des milliers de trips).
    trip_route = {}
    seen_dir = set()
    for t in _read(zf, "trips.txt"):
        key = (t["route_id"], t.get("direction_id", ""))
        if key in seen_dir:
            continue
        seen_dir.add(key)
        trip_route[t["trip_id"]] = t["route_id"]

    # 3. stop_id -> (nom station, lat, lon)
    stops = {}
    for s in _read(zf, "stops.txt"):
        try:
            stops[s["stop_id"]] = (s["stop_name"].strip(),
                                   float(s["stop_lat"]), float(s["stop_lon"]))
        except (KeyError, ValueError):
            continue

    # 4. Un seul passage sur stop_times (gros fichier), filtré sur les trips retenus.
    station_lines = defaultdict(set)   # nom station -> {lignes}
    station_pts = defaultdict(list)    # nom station -> [(lat, lon)]
    station_tram = defaultdict(bool)
    for st in _read(zf, "stop_times.txt"):
        route_id = trip_route.get(st["trip_id"])
        if route_id is None:
            continue
        stop = stops.get(st["stop_id"])
        if stop is None:
            continue
        name, lat, lon = stop
        line, is_tram = routes.get(route_id, ("", False))
        if line:
            station_lines[name].add(line)
        station_pts[name].append((lat, lon))
        if is_tram:
            station_tram[name] = True

    stations = []
    for name, pts in station_pts.items():
        lat = sum(p[0] for p in pts) / len(pts)
        lon = sum(p[1] for p in pts) / len(pts)
        stations.append({
            "name": name, "lat": round(lat, 6), "lon": round(lon, 6),
            "lines": sorted(station_lines[name]), "tram": station_tram[name]})
    stations.sort(key=lambda s: s["name"])
    return stations


def main() -> None:
    if len(sys.argv) > 1:
        zip_bytes = Path(sys.argv[1]).read_bytes()
    else:
        print(f"Téléchargement {GTFS_URL} ...")
        zip_bytes = httpclient.get(httpclient.make_session(), GTFS_URL).content
    stations = build(zip_bytes)
    OUT.write_text(json.dumps(stations, ensure_ascii=False), encoding="utf-8")
    trams = sum(1 for s in stations if s["tram"])
    print(f"{len(stations)} stations écrites dans {OUT.name} ({trams} desservies par tram).")


if __name__ == "__main__":
    main()
