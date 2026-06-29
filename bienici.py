"""Source Bien'ici — appartements en location (couverture AGENCES).

Agrège les flux des agences. API JSON publique (realEstateAds.json), filtrée par
zoneId. HTTP simple, pas d'anti-bot. Strasbourg = -71033 (couvre le bassin).
"""
import json

import httpclient
from models import Listing

API_URL = "https://www.bienici.com/realEstateAds.json"
SOURCE = "bienici"
PER_PAGE = 24
MAX_PAGES = 5


def _filters(zone_id: str, page: int) -> dict:
    return {
        "size": PER_PAGE,
        "from": (page - 1) * PER_PAGE,
        "filterType": "rent",
        "propertyType": ["flat"],
        "page": page,
        "sortBy": "publicationDate",
        "sortOrder": "desc",
        "onTheMarket": [True],
        "zoneIdsByTypes": {"zoneIds": [zone_id]},
    }


def _normalize(ad: dict) -> Listing:
    rooms = ad.get("roomsQuantity") or 0
    surface = ad.get("surfaceArea")
    description = ad.get("description") or ""
    title = ad.get("title") or (
        f"Appartement {rooms or '?'} pièces {round(surface) if surface else '?'} m²")
    return Listing(
        source=SOURCE, id=str(ad.get("id")),
        url=f"https://www.bienici.com/annonce/{ad.get('id')}", title=title,
        rent=round(ad["price"]) if ad.get("price") else None,
        rooms=int(rooms) if rooms else 0,
        surface=int(round(surface)) if surface else None,
        city=ad.get("city", ""), furnished="meubl" in description.lower(),
        description=description[:200], published_at=ad.get("publicationDate", ""))


def fetch_all_listings(zone_id: str) -> list[Listing]:
    session = httpclient.make_session()
    headers = {"X-Requested-With": "XMLHttpRequest",
               "Referer": "https://www.bienici.com/recherche/location"}
    listings: list[Listing] = []
    for page in range(1, MAX_PAGES + 1):
        params = {"filters": json.dumps(_filters(zone_id, page)),
                  "extensionType": "extendedIfNoResult"}
        response = httpclient.get(session, API_URL, params=params, headers=headers)
        if response.status_code != 200:
            break
        ads = response.json().get("realEstateAds", [])
        if not ads:
            break
        for ad in ads:
            try:
                listings.append(_normalize(ad))
            except Exception:
                continue
    return listings


if __name__ == "__main__":
    for item in fetch_all_listings("-71033")[:8]:
        print(f"  {item.rent}€ | {item.size_label} | {item.surface}m² | {item.url}")
