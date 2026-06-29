"""Source PAP (pap.fr) — appartements en location, de particulier à particulier.

Annonces dans le HTML (pas de JS, pas d'anti-bot). Codes ville :
  Strasbourg   = /annonce/locations-appartement-strasbourg-67-g43623
  Schiltigheim = /annonce/locations-appartement-schiltigheim-67300-g34791
"""
import re

from bs4 import BeautifulSoup

import httpclient
from models import Listing

BASE = "https://www.pap.fr"
DEFAULT_CITY_PATH = "/annonce/locations-appartement-strasbourg-67-g43623"
SOURCE = "pap"
MAX_PAGES = 10


def _page_url(city_path: str, page: int) -> str:
    return BASE + city_path + (f"-{page}" if page > 1 else "")


def _to_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _parse_card(anchor) -> Listing | None:
    href = anchor.get("href", "")
    if "/annonces/" not in href:
        return None
    id_match = re.search(r"-r(\d+)", href)
    if not id_match:
        return None

    price_el = anchor.select_one(".item-price")
    title_el = anchor.select_one(".h1")
    title = title_el.get_text(strip=True) if title_el else "Appartement Strasbourg"
    tags = [li.get_text(strip=True) for li in anchor.select(".item-tags li")]
    rooms = next((_to_int(t) for t in tags if "pièce" in t), None) or 0
    surface = next((_to_int(t) for t in tags if "m²" in t), None)

    body = anchor.find_parent("div", class_="item-body")
    desc_el = body.select_one(".item-description") if body else None
    description = desc_el.get_text(" ", strip=True) if desc_el else ""

    return Listing(
        source=SOURCE, id=id_match.group(1), url=BASE + href, title=title,
        rent=_to_int(price_el.get_text()) if price_el else None,
        rooms=rooms, surface=surface, city="Strasbourg",
        furnished="meubl" in f"{title} {description}".lower(),
        description=description[:200])


def fetch_all_listings(city_path: str = DEFAULT_CITY_PATH) -> list[Listing]:
    session = httpclient.make_session()
    listings: list[Listing] = []
    seen_ids: set = set()
    for page in range(1, MAX_PAGES + 1):
        response = httpclient.get(session, _page_url(city_path, page))
        if response.status_code != 200:
            break
        anchors = BeautifulSoup(response.text, "html.parser").select("a.item-title")
        new_on_page = 0
        for anchor in anchors:
            try:
                listing = _parse_card(anchor)
            except Exception:
                continue
            if not listing or listing.id in seen_ids:
                continue
            seen_ids.add(listing.id)
            listings.append(listing)
            new_on_page += 1
        if new_on_page == 0:
            break
    return listings


if __name__ == "__main__":
    for item in fetch_all_listings()[:8]:
        print(f"  {item.rent}€ | {item.size_label} | {item.surface}m² | {item.url}")
