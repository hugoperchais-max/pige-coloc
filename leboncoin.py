"""Source LeBonCoin — locations.

Protégé par DataDome ; une requête HTTP simple (impersonation TLS) passe souvent
à basse fréquence. Annonces dans le JSON __NEXT_DATA__. Tri par date (sort=time)
pour que les nouvelles soient en page 1. ⚠️ Peut renvoyer vide depuis une IP
datacenter (GitHub Actions) — l'orchestrateur gère ça (source sautée).
"""
import json
import re

import httpclient
from models import Listing

BASE = "https://www.leboncoin.fr/recherche"
CATEGORY_LOCATIONS = "10"
SOURCE = "leboncoin"
MAX_PAGES = 3
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def _to_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _attr_map(ad: dict) -> dict:
    return {a.get("key"): (a.get("value"), a.get("value_label"))
            for a in ad.get("attributes", [])}


def _extract_ads(html: str) -> list[dict]:
    match = NEXT_DATA_RE.search(html)
    if not match:
        return []
    data = json.loads(match.group(1))
    return (data.get("props", {}).get("pageProps", {})
                .get("searchData", {}).get("ads", []) or [])


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize(ad: dict) -> Listing:
    attrs = _attr_map(ad)
    furnished_label = (attrs.get("furnished", (None, ""))[1] or "")
    price = ad.get("price")
    rent = price[0] if isinstance(price, list) and price else price
    loc = ad.get("location", {})
    return Listing(
        source=SOURCE, id=str(ad.get("list_id")), url=ad.get("url", ""),
        title=ad.get("subject", "Annonce"), rent=_to_int(rent),
        rooms=_to_int(attrs.get("rooms", (None, None))[0]) or 0,
        surface=_to_int(attrs.get("square", (None, None))[0]),
        city=loc.get("city", ""), district=loc.get("district"),
        lat=_to_float(loc.get("lat")), lng=_to_float(loc.get("lng")),
        furnished="non" not in furnished_label.lower() and bool(furnished_label),
        description=(ad.get("body") or "")[:200],
        published_at=ad.get("first_publication_date", ""))


def fetch_all_listings(location: str) -> list[Listing]:
    session = httpclient.make_session()
    listings: list[Listing] = []
    for page in range(1, MAX_PAGES + 1):
        params = {"category": CATEGORY_LOCATIONS, "locations": location,
                  "sort": "time", "order": "desc"}
        if page > 1:
            params["page"] = str(page)
        response = httpclient.get(session, BASE, params=params)
        if response.status_code != 200:
            break
        ads = _extract_ads(response.text)
        if not ads:
            break
        for ad in ads:
            try:
                listings.append(_normalize(ad))
            except Exception:
                continue
    return listings


if __name__ == "__main__":
    for item in fetch_all_listings("Strasbourg_67000")[:8]:
        print(f"  {item.rent}€ | {item.size_label} | {item.surface}m² | {item.url}")
