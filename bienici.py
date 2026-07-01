"""Source Bien'ici — appartements en location (couverture AGENCES).

Agrège les flux des agences. API JSON publique (realEstateAds.json), filtrée par
zoneId. HTTP simple, pas d'anti-bot. Strasbourg = -71033 (couvre le bassin).
"""
import json

import httpclient
from models import Listing, detect_furnished

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


def _center_of(ad: dict) -> tuple[float | None, float | None]:
    """Centre de la zone floutée (bbox = [lngMin, latMin, lngMax, latMax]),
    précis à ~50 m. Fallback sur un éventuel champ direct lat/lng."""
    bbox = (ad.get("blurInfo") or {}).get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return (bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2
    return ad.get("latitude"), ad.get("longitude")


def _normalize(ad: dict) -> Listing:
    rooms = ad.get("roomsQuantity") or 0
    surface = ad.get("surfaceArea")
    description = ad.get("description") or ""
    title = ad.get("title") or (
        f"Appartement {rooms or '?'} pièces {round(surface) if surface else '?'} m²")
    lat, lng = _center_of(ad)
    district = (ad.get("district") or {}).get("name")
    photos = ad.get("photos") or []
    photo = photos[0].get("url_photo") if photos and isinstance(photos[0], dict) else None
    return Listing(
        source=SOURCE, id=str(ad.get("id")),
        url=f"https://www.bienici.com/annonce/{ad.get('id')}", title=title,
        rent=round(ad["price"]) if ad.get("price") else None,
        rooms=int(rooms) if rooms else 0,
        surface=int(round(surface)) if surface else None,
        city=ad.get("city", ""), district=district, lat=lat, lng=lng,
        furnished=detect_furnished(f"{title} {description}"),
        description=description[:200], published_at=ad.get("publicationDate", ""),
        photo=photo)


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
