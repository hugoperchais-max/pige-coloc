"""Estimation du temps de trajet en transports en commun (réseau CTS Strasbourg).

PAS un calculateur d'itinéraire exact (pas de moteur horaire) : une estimation
honnête à ±5-10 min, largement suffisante pour trier des annonces. Repose sur
`cts_transit.json` (stations + lignes, généré par build_transit.py), aucune API,
aucune clé, aucun quota.

Modèle : marche jusqu'à la station la plus proche + attente + trajet véhicule
(vitesse commerciale) + correspondance si pas de ligne directe + marche d'arrivée.
"""
import json
import math
from pathlib import Path

_STATIONS = json.loads((Path(__file__).parent / "cts_transit.json").read_text(encoding="utf-8"))

WALK_SPEED_KMH = 4.8          # marche à pied
WALK_DETOUR = 1.3            # les rues ne vont pas en ligne droite
VEHICLE_SPEED_KMH = 17.0      # vitesse commerciale porte-à-porte (tram+bus urbain)
WAIT_MIN = 4.0               # attente moyenne à l'arrêt
TRANSFER_MIN = 7.0          # pénalité si pas de ligne directe (1 correspondance)
FAR_FROM_TRANSIT_M = 900     # au-delà : annonce jugée mal desservie


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nearest(lat: float, lon: float) -> tuple[dict, float]:
    """Station la plus proche + distance à pied réelle (mètres)."""
    best, best_d = None, float("inf")
    for st in _STATIONS:
        d = _haversine_m(lat, lon, st["lat"], st["lon"])
        if d < best_d:
            best, best_d = st, d
    return best, best_d * WALK_DETOUR


def _walk_min(distance_m: float) -> float:
    return distance_m / 1000 / WALK_SPEED_KMH * 60


def estimate(o_lat: float, o_lon: float, d_lat: float, d_lon: float) -> dict:
    """Estimation porte-à-porte entre une annonce et une destination.

    Retourne {minutes, stop (arrêt de départ), stop_walk_m, direct, served}.
    """
    origin, o_walk_m = _nearest(o_lat, o_lon)
    dest, d_walk_m = _nearest(d_lat, d_lon)

    if origin["name"] == dest["name"]:              # même station -> à pied
        walk_direct = _haversine_m(o_lat, o_lon, d_lat, d_lon) * WALK_DETOUR
        return {"minutes": round(_walk_min(walk_direct)), "stop": origin["name"],
                "stop_walk_m": round(o_walk_m), "direct": True, "served": True}

    veh_km = _haversine_m(origin["lat"], origin["lon"], dest["lat"], dest["lon"]) / 1000
    veh_min = veh_km / VEHICLE_SPEED_KMH * 60
    direct = bool(set(origin["lines"]) & set(dest["lines"]))
    total = (_walk_min(o_walk_m) + WAIT_MIN + veh_min
             + (0 if direct else TRANSFER_MIN) + _walk_min(d_walk_m))
    return {"minutes": round(total), "stop": origin["name"],
            "stop_walk_m": round(o_walk_m), "direct": direct,
            "served": o_walk_m <= FAR_FROM_TRANSIT_M}


def enrich(lat: float, lon: float, campuses: dict) -> dict:
    """Calcule les trajets vers un ensemble de campus {clé: {lat, lon, label}}.

    Retourne {trips: {label: minutes}, stop, stop_walk_m, served}.
    """
    served = None
    stop = stop_walk = None
    trips = {}
    for campus in campuses.values():
        e = estimate(lat, lon, campus["lat"], campus["lon"])
        trips[campus["label"]] = e["minutes"]
        if served is None:                          # même arrêt de départ pour tous
            served, stop, stop_walk = e["served"], e["stop"], e["stop_walk_m"]
    return {"trips": trips, "stop": stop, "stop_walk_m": stop_walk, "served": bool(served)}
