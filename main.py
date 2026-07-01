"""Orchestrateur du bot de pige.

Pipeline : fetch (parallèle, mis en cache, retries) -> filtre par profil
-> dédup inter-sources -> alerte Telegram. Tourne en local ou sur GitHub Actions.
"""
import html
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import bienici
import leboncoin
import notify
import pap
import transit
from models import Listing

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("pige")

# Registre des sources : nom dans config.json -> module exposant fetch_all_listings(query).
SOURCE_MODULES = {"pap": pap, "leboncoin": leboncoin, "bienici": bienici}

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
SEEN_PATH = HERE / "seen.json"
PREVIEW_PER_PROFILE = 3
MAX_WORKERS = 6
MAX_ALERTS_PER_RUN = 25
SEND_DELAY_SECONDS = 0.7
MAX_SEEN = 8000


# --------------------------------------------------------------------------- #
# Config & état
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_seen_order() -> list:
    if SEEN_PATH.exists():
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else sorted(data)
    return []


def save_seen_order(order: list) -> None:
    SEEN_PATH.write_text(json.dumps(order[-MAX_SEEN:]), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Récupération : parallèle, mise en cache, retries
# --------------------------------------------------------------------------- #
def _fetch_one(source_name: str, query: str) -> list[Listing]:
    try:
        return SOURCE_MODULES[source_name].fetch_all_listings(query)
    except Exception as error:
        log.warning("source %s(%s) en échec: %s", source_name, query, error)
        return []


def fetch_all_sources(config: dict) -> dict:
    """Récupère chaque couple (source, requête) UNE seule fois, en parallèle."""
    pairs = {(name, query)
             for profile in config["profiles"]
             for name, query in profile.get("sources", {}).items()
             if name in SOURCE_MODULES}

    results: dict = {}
    started = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, name, query): (name, query)
                   for name, query in pairs}
        for future in as_completed(futures):
            pair = futures[future]
            results[pair] = future.result()
            log.info("· %s(%s) : %d annonces", pair[0], pair[1], len(results[pair]))
    log.info("Fetch de %d sources en %.1fs.", len(pairs), time.time() - started)
    return results


# --------------------------------------------------------------------------- #
# Filtrage & déduplication inter-sources
# --------------------------------------------------------------------------- #
def collect_matches(config: dict, fetched: dict) -> dict:
    """{clé annonce -> Listing} pour celles qui matchent au moins un profil."""
    matched: dict = {}
    for profile in config["profiles"]:
        for source_name, query in profile.get("sources", {}).items():
            kept = 0
            for listing in fetched.get((source_name, query), []):
                if not listing.matches(profile):
                    continue
                kept += 1
                existing = matched.get(listing.key)
                if existing is not None:
                    if profile["label"] not in existing.profiles:
                        existing.profiles.append(profile["label"])
                else:
                    listing.profiles = [profile["label"]]
                    matched[listing.key] = listing
            log.info("[%s / %s] %d correspondent.", profile["label"], source_name, kept)
    return matched


def enrich_transit(config: dict, representatives: list[Listing]) -> None:
    """Ajoute à chaque bien géolocalisé son temps de trajet vers les campus de
    ses profils (in place). Les biens sans coordonnées (souvent PAP) sont laissés
    tels quels — on ne les jette pas, on ne peut juste pas estimer leur trajet."""
    campuses = config.get("campuses", {})
    if not campuses:
        return
    to_campus = {p["label"]: p.get("transit_to", []) for p in config["profiles"]}
    for listing in representatives:
        if listing.lat is None or listing.lng is None:
            continue
        keys = {k for label in listing.profiles for k in to_campus.get(label, [])}
        sub = {k: campuses[k] for k in keys if k in campuses}
        if sub:
            listing.transit = transit.enrich(listing.lat, listing.lng, sub)


def passes_transit(listing: Listing, config: dict) -> bool:
    """Filtre géo OPTIONNEL. Vrai (gardé) sauf si TOUS les profils du bien fixent
    un `max_transit_min` et qu'aucun n'est satisfait. Sans seuil configuré (défaut),
    ne jette jamais rien. Un bien sans géoloc n'est jamais écarté ici."""
    profile_by_label = {p["label"]: p for p in config["profiles"]}
    campuses = config.get("campuses", {})
    trips = (listing.transit or {}).get("trips", {})
    for label in listing.profiles:
        prof = profile_by_label.get(label, {})
        threshold = prof.get("max_transit_min")
        if threshold is None:
            return True                      # un profil sans seuil garde toujours
        times = [trips.get(campuses[k]["label"]) for k in prof.get("transit_to", [])
                 if k in campuses and trips.get(campuses[k]["label"]) is not None]
        if not times or min(times) <= threshold:
            return True                      # pas de géoloc jugeable, ou sous le seuil
    return False


def merge_cross_source(matched: dict) -> list[Listing]:
    """Fusionne un même bien cross-posté sur des sources DIFFÉRENTES (jamais
    deux annonces d'une même source = probablement deux biens distincts)."""
    representatives: list[Listing] = []
    by_fingerprint: dict = {}
    for listing in matched.values():
        fingerprint = listing.fingerprint()
        rep = by_fingerprint.get(fingerprint) if fingerprint is not None else None
        if rep is not None and rep.source != listing.source:
            rep.member_keys.append(listing.key)
            if listing.url and listing.url not in rep.also:
                rep.also.append(listing.url)
            for label in listing.profiles:
                if label not in rep.profiles:
                    rep.profiles.append(label)
        else:
            listing.member_keys = [listing.key]
            if fingerprint is not None:
                by_fingerprint[fingerprint] = listing
            representatives.append(listing)
    return representatives


# --------------------------------------------------------------------------- #
# Formatage & envoi
# --------------------------------------------------------------------------- #
def format_alert(listing: Listing) -> str:
    esc = html.escape  # neutralise <, >, & (sinon Telegram 400)
    rent = listing.rent if listing.rent is not None else "?"
    surface = listing.surface if listing.surface else "?"
    place = ", ".join(p for p in (listing.street, listing.district, listing.city) if p)
    location = esc(place)
    furnished = "meublé" if listing.furnished else "non meublé"
    age = listing.age_label()
    headline = f"🎯 <i>{esc(' + '.join(listing.profiles))}</i>"
    if age:
        headline += f"  ·  🕐 <b>{age}</b>"
    lines = [headline,
             f"🏠 <b>{esc(listing.title)}</b>",
             f"💶 {rent} €/mois · {esc(listing.size_label)} · {surface} m² · {furnished}",
             f"📍 {location}"]
    transit_line = _format_transit(listing)
    if transit_line:
        lines.append(transit_line)
    lines.append(esc(listing.url))
    if listing.also:
        lines.append("↘️ aussi : " + " · ".join(esc(u) for u in listing.also))
    return "\n".join(lines)


def _format_transit(listing: Listing) -> str:
    """Deux lignes : estimation rapide (tri) + lien(s) itinéraire réel Google Maps.
    Vide si pas de géoloc."""
    info = listing.transit
    if not info or not info.get("trips"):
        return ""
    esc = html.escape
    trips = " · ".join(f"{esc(label)} ~{mins} min" for label, mins in info["trips"].items())
    stop, walk = info.get("stop"), info.get("stop_walk_m")
    suffix = f" (arrêt {esc(stop)}, {walk} m)" if stop else ""
    warn = "" if info.get("served") else "  ⚠️ mal desservi"
    lines = [f"🚇 {trips}{suffix}{warn}"]
    links = info.get("links") or {}
    if links:
        itineraires = " · ".join(
            f'<a href="{html.escape(url, quote=True)}">{esc(label)}</a>'
            for label, url in links.items())
        lines.append(f"🗺️ Itinéraire réel : {itineraires}")
    return "\n".join(lines)


def _preview_per_profile(new_matches: list[Listing]) -> list[Listing]:
    """Aperçu 1er run : quelques biens PAR profil (sinon on ne verrait que les
    studios solo les moins chers, jamais le T3 coloc)."""
    selected, counts = [], {}
    for listing in new_matches:
        label = listing.profiles[0]
        if counts.get(label, 0) < PREVIEW_PER_PROFILE:
            selected.append(listing)
            counts[label] = counts.get(label, 0) + 1
    return selected


def _tokens(listing: Listing) -> list:
    """Jetons d'identité pour l'anti-spam : les clés source:id + l'empreinte du
    bien. L'empreinte permet de reconnaître un bien REPUBLIÉ (nouvel id) déjà vu."""
    tokens = list(listing.member_keys)
    fingerprint = listing.fingerprint()
    if fingerprint is not None:
        tokens.append("fp:" + ":".join(map(str, fingerprint)))
    return tokens


def main() -> None:
    config = load_config()
    first_run = not SEEN_PATH.exists()
    seen_order = load_seen_order()
    seen = set(seen_order)

    def remember(listing: Listing) -> None:
        for token in _tokens(listing):
            if token not in seen:
                seen.add(token)
                seen_order.append(token)

    fetched = fetch_all_sources(config)
    representatives = merge_cross_source(collect_matches(config, fetched))
    enrich_transit(config, representatives)
    representatives = [r for r in representatives if passes_transit(r, config)]
    new_matches = [r for r in representatives
                   if not any(tok in seen for tok in _tokens(r))]
    # Plus récentes d'abord (date connue avant date inconnue) ; prix en départage.
    _oldest = datetime.min.replace(tzinfo=timezone.utc)
    new_matches.sort(key=lambda l: (l.published_dt() or _oldest, -(l.rent or 0)),
                     reverse=True)
    log.info("%d biens uniques, %d nouveaux.", len(representatives), len(new_matches))

    to_send = _preview_per_profile(new_matches) if first_run else new_matches
    sent = 0
    try:
        if first_run:
            notify.send_message(
                "✅ Bot pige activé.\n"
                f"{len(representatives)} biens correspondent à tes critères "
                f"(après dédup inter-sources).\nAperçu ci-dessous — ensuite, "
                f"seulement les NOUVEAUX.")
        for listing in to_send:
            if sent >= MAX_ALERTS_PER_RUN:
                log.info("Plafond %d atteint, le reste au prochain passage.", MAX_ALERTS_PER_RUN)
                break
            if notify.send_message(format_alert(listing)):
                remember(listing)  # marqué vu SEULEMENT si envoyé
                sent += 1
                time.sleep(SEND_DELAY_SECONDS)
            else:
                log.warning("Telegram indisponible : arrêt, le reste partira au prochain run.")
                break
        if first_run:  # amorce tout le stock pour ne plus jamais flooder
            for rep in representatives:
                remember(rep)
    finally:
        save_seen_order(seen_order)  # toujours sauvegardé, même en cas d'erreur
        log.info("%d alerte(s) envoyée(s). seen.json = %d entrées.", sent, len(seen_order))


if __name__ == "__main__":
    main()
