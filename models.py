"""Schéma typé d'une annonce + sa logique métier.

Centralise ce qui était dispersé : parsing du nombre de pièces, empreinte de
déduplication, et critères de correspondance. Un seul endroit = un seul contrat.
"""
import calendar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def _last_sunday(year: int, month: int) -> int:
    return max(week[calendar.SUNDAY] for week in calendar.monthcalendar(year, month))


def _paris_is_summer(dt: datetime) -> bool:
    """Heure d'été européenne : dernier dimanche de mars → dernier d'octobre."""
    start = datetime(dt.year, 3, _last_sunday(dt.year, 3), 2)
    end = datetime(dt.year, 10, _last_sunday(dt.year, 10), 3)
    return start <= dt < end


_UNFURNISHED = ("non meublé", "non-meublé", "non meuble", "vide", "dégarni", "nu ")


def detect_furnished(text: str) -> bool:
    """True seulement si 'meublé' apparaît SANS négation. Corrige le piège
    'non meublé' (qui contient 'meubl' et passait à tort pour meublé)."""
    low = (text or "").lower()
    if any(neg in low for neg in _UNFURNISHED):
        return False
    return "meubl" in low


@dataclass
class Listing:
    source: str
    id: str
    url: str
    title: str = "Annonce"
    rent: int | None = None          # loyer mensuel total (€)
    rooms: int = 0                   # nombre de pièces (0 = inconnu)
    surface: int | None = None       # m²
    city: str = ""
    street: str | None = None
    district: str | None = None      # quartier (ex. "Neudorf", "Kléber-Gare")
    lat: float | None = None         # latitude (approx. selon la source)
    lng: float | None = None         # longitude
    furnished: bool = False
    description: str = ""
    published_at: str = ""
    photo: str | None = None         # URL de la photo principale (si dispo)
    # Champs remplis par l'orchestrateur (pipeline), pas par les sources :
    profiles: list = field(default_factory=list)   # profils satisfaits
    also: list = field(default_factory=list)        # autres liens (cross-post)
    member_keys: list = field(default_factory=list)  # clés fusionnées
    transit: dict = field(default_factory=dict)      # {campus: minutes} + arrêt proche

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def size_label(self) -> str:
        return f"{self.rooms} pièces" if self.rooms else ""

    def published_dt(self) -> datetime | None:
        """Date de publication en UTC, quel que soit le format source.
        Bien'ici = ISO 8601 UTC (…Z) ; LeBonCoin = 'Y-m-d H:M:S' en heure de Paris."""
        raw = (self.published_at or "").strip()
        if not raw:
            return None
        try:
            if "T" in raw or raw.endswith("Z"):
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            naive = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")   # heure de Paris
            offset = 2 if _paris_is_summer(naive) else 1
            return (naive - timedelta(hours=offset)).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def age_label(self) -> str:
        """'il y a 8 min' / 'il y a 2 h' / 'il y a 3 j', ou '' si date inconnue."""
        dt = self.published_dt()
        if dt is None:
            return ""
        minutes = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))
        if minutes < 60:
            return f"il y a {minutes} min"
        if minutes < 1440:
            return f"il y a {minutes // 60} h"
        return f"il y a {minutes // 1440} j"

    def fingerprint(self) -> tuple | None:
        """Empreinte de dédup inter-sources. None si trop incomplète pour être sûre."""
        if not self.surface or not self.rooms or not self.rent:
            return None
        return (self.rooms, int(self.surface), round(self.rent / 10) * 10,
                self.city.strip().lower()[:20])

    def matches(self, profile: dict) -> bool:
        rent = self.rent or 0
        if rent < profile.get("min_rent", 250):       # plancher anti-bruit
            return False
        if profile.get("max_rent") and rent > profile["max_rent"]:
            return False
        if self.rooms < profile.get("min_rooms", 0):
            return False
        if profile.get("max_rooms", 0) and self.rooms > profile["max_rooms"]:
            return False
        if (self.surface or 0) < profile.get("min_surface", 0):
            return False
        # Garde anti "prix par personne" : un loyer total à Strasbourg fait
        # 11-17 €/m² ; sous le seuil, c'est presque toujours un prix par
        # colocataire présenté comme le loyer de l'appart entier.
        floor = profile.get("min_rent_per_m2")
        if floor and self.surface and rent and rent / self.surface < floor:
            return False
        if profile.get("furnished_only") and not self.furnished:
            return False
        if profile.get("unfurnished_only") and self.furnished:
            return False

        haystack = f"{self.title} {self.description} {self.street or ''}".lower()
        if any(w.lower() in haystack for w in profile.get("exclude_keywords", [])):
            return False
        includes = profile.get("include_keywords", [])
        if includes and not any(w.lower() in haystack for w in includes):
            return False
        return True
