"""Schéma typé d'une annonce + sa logique métier.

Centralise ce qui était dispersé : parsing du nombre de pièces, empreinte de
déduplication, et critères de correspondance. Un seul endroit = un seul contrat.
"""
from dataclasses import dataclass, field


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
    furnished: bool = False
    description: str = ""
    published_at: str = ""
    # Champs remplis par l'orchestrateur (pipeline), pas par les sources :
    profiles: list = field(default_factory=list)   # profils satisfaits
    also: list = field(default_factory=list)        # autres liens (cross-post)
    member_keys: list = field(default_factory=list)  # clés fusionnées

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def size_label(self) -> str:
        return f"{self.rooms} pièces" if self.rooms else ""

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
