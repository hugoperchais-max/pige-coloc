"""Tests de non-régression. Lancer : `python test_pige.py` (sans réseau)."""
import main
from models import Listing, detect_furnished


def _listing(**kw) -> Listing:
    base = dict(source="pap", id="1", url="https://x/1", title="Appartement",
                rent=900, rooms=3, surface=70, city="Strasbourg")
    base.update(kw)
    return Listing(**base)


COLOC = {"label": "coloc", "min_rent": 400, "max_rent": 1000, "min_rooms": 3,
         "max_rooms": 0, "exclude_keywords": ["bail mobilité"]}
SOLO = {"label": "solo", "min_rent": 300, "max_rent": 800, "min_rooms": 1,
        "max_rooms": 2}


def test_min_rent_floor():
    assert _listing(rent=60).matches(COLOC) is False
    assert _listing(rent=900).matches(COLOC) is True


def test_max_rent():
    assert _listing(rent=1500).matches(COLOC) is False


def test_rooms_bounds():
    studio = _listing(rooms=1, rent=500)
    assert studio.matches(COLOC) is False   # < 3 pièces
    assert studio.matches(SOLO) is True      # 1-2 pièces OK
    assert _listing(rooms=4, rent=700).matches(SOLO) is False  # > max_rooms 2


def test_unfurnished_only():
    prof = {**SOLO, "unfurnished_only": True}
    assert _listing(rooms=2, rent=600, furnished=True).matches(prof) is False
    assert _listing(rooms=2, rent=600, furnished=False).matches(prof) is True


def test_exclude_keywords():
    assert _listing(description="Joli T3, bail mobilité 6 mois").matches(COLOC) is False


def test_cross_source_merge_only_different_sources():
    a = _listing(source="leboncoin", id="lbc1", profiles=["coloc"])
    b = _listing(source="bienici", id="bi1", profiles=["coloc"])    # même bien
    c = _listing(source="leboncoin", id="lbc2", profiles=["coloc"])  # même empreinte, même source
    reps = main.merge_cross_source({a.key: a, b.key: b, c.key: c})
    assert len(reps) == 2, f"attendu 2 représentants, obtenu {len(reps)}"
    merged = [r for r in reps if len(r.member_keys) == 2]
    assert merged and "bienici:bi1" in merged[0].member_keys


def test_fingerprint_none_when_incomplete():
    assert _listing(surface=None).fingerprint() is None
    assert _listing().fingerprint() is not None


def test_format_alert_escapes_html():
    out = main.format_alert(_listing(district="Halles <R&D>", profiles=["coloc"],
                                     url="https://x/a?b=1&c=2"))
    assert "<R&D>" not in out and "&lt;R&amp;D&gt;" in out
    assert "https://x/a?b=1&c=2" not in out  # l'URL est en bouton, pas dans le texte


def test_transit_line_shown_when_present():
    l = _listing(profiles=["coloc"], rent=930, surface=66,
                 transit={"trips": {"IUT Schilt.": 22}, "stop": "Gare Centrale",
                          "stop_walk_m": 250, "served": True,
                          "links": {"IUT Schilt.": "https://maps/x?a=1&b=2"}})
    out = main.format_alert(l)
    assert "IUT Schilt. 22 min 🟡" in out and "Gare Centrale" in out
    # l'itinéraire est désormais un BOUTON, pas dans le texte
    buttons = main.build_buttons(l)
    assert buttons[0][0]["url"] == "https://maps/x?a=1&b=2"


def test_transit_line_absent_without_geo():
    out = main.format_alert(_listing(profiles=["coloc"]))  # transit vide par défaut
    assert "🚊" not in out


def test_feu_colors():
    assert main._feu(15) == "🟢" and main._feu(30) == "🟡" and main._feu(50) == "🔴"


def test_visale_badge_share_under_cap():
    coloc = main.format_alert(_listing(profiles=["coloc"], rent=900, surface=66, tenants=2))
    assert "Éligible Visale" in coloc and "~450" in coloc          # 900/2 = 450 < 600
    solo = main.format_alert(_listing(profiles=["solo"], rent=750, surface=30, tenants=1))
    assert "Éligible Visale" not in solo                            # 750 > 600
    price_per_m2 = _listing(profiles=["coloc"], rent=930, surface=66)
    assert "14 €/m²" in main.format_alert(price_per_m2)


def test_buttons_include_annonce_link():
    l = _listing(profiles=["coloc"], url="https://x/annonce/1")
    rows = main.build_buttons(l)
    assert any(b["url"] == "https://x/annonce/1" for row in rows for b in row)


def test_passes_transit_no_threshold_keeps_all():
    cfg = {"profiles": [{"label": "coloc", "transit_to": ["iut"]}],
           "campuses": {"iut": {"label": "IUT Schilt.", "lat": 48.6, "lon": 7.7}}}
    far = _listing(profiles=["coloc"], transit={"trips": {"IUT Schilt.": 90}})
    assert main.passes_transit(far, cfg) is True   # aucun seuil -> jamais écarté


def test_passes_transit_threshold_filters():
    cfg = {"profiles": [{"label": "coloc", "transit_to": ["iut"], "max_transit_min": 40}],
           "campuses": {"iut": {"label": "IUT Schilt.", "lat": 48.6, "lon": 7.7}}}
    far = _listing(profiles=["coloc"], transit={"trips": {"IUT Schilt.": 90}})
    near = _listing(profiles=["coloc"], transit={"trips": {"IUT Schilt.": 20}})
    no_geo = _listing(profiles=["coloc"])          # pas de géoloc -> jamais écarté
    assert main.passes_transit(far, cfg) is False
    assert main.passes_transit(near, cfg) is True
    assert main.passes_transit(no_geo, cfg) is True


def test_published_dt_parses_both_formats():
    from datetime import timezone
    # Bien'ici : ISO UTC
    b = _listing(published_at="2026-07-01T09:42:57.026Z").published_dt()
    assert b is not None and b.tzinfo is not None and b.hour == 9
    # LeBonCoin : heure de Paris (été = UTC+2) -> 12:48 Paris = 10:48 UTC
    l = _listing(published_at="2026-07-01 12:48:06").published_dt()
    assert l is not None and l.astimezone(timezone.utc).hour == 10
    # inconnu
    assert _listing(published_at="").published_dt() is None


def test_age_label_buckets():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert "min" in _listing(published_at=recent).age_label()
    assert _listing(published_at="").age_label() == ""


def test_alert_shows_age():
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    out = main.format_alert(_listing(profiles=["coloc"], published_at=recent))
    assert "🕐" in out and "min" in out


def test_detect_furnished_handles_negation():
    assert detect_furnished("Appartement non meublé, lumineux") is False
    assert detect_furnished("Appartement non-meublé") is False
    assert detect_furnished("Bel appartement meublé") is True
    assert detect_furnished("Logement vide") is False
    assert detect_furnished("T2 lumineux") is False


def test_min_rent_per_m2_floor():
    prof = {**COLOC, "min_rent_per_m2": 8}
    # 498€ pour 80m² = 6€/m² -> prix par personne, écarté
    assert _listing(rent=498, rooms=6, surface=80).matches(prof) is False
    # 930€ pour 66m² = 14€/m² -> loyer réel, gardé
    assert _listing(rent=930, rooms=3, surface=66).matches(prof) is True


def test_solo_excludes_chamber_and_coloc():
    solo = {"label": "solo", "min_rent": 300, "max_rent": 800, "min_rooms": 1,
            "max_rooms": 2, "min_surface": 18,
            "exclude_keywords": ["colocation", "chambre meublée"]}
    assert _listing(rooms=1, rent=550, surface=12,
                    title="COLOCATION STRASBOURG 1 pièce").matches(solo) is False
    assert _listing(rooms=1, rent=520, surface=10,
                    title="Chambre 1 pièce").matches(solo) is False  # 10m² < 18
    assert _listing(rooms=2, rent=650, surface=45,
                    title="Appartement 2 pièces").matches(solo) is True  # vrai T2


def test_tokens_include_fingerprint_for_republication():
    l = _listing(source="bienici", id="A1", rooms=3, surface=66, rent=930,
                 city="Strasbourg", member_keys=["bienici:A1"])
    toks = main._tokens(l)
    assert "bienici:A1" in toks
    assert any(t.startswith("fp:") for t in toks)          # empreinte présente
    # même bien republié avec un AUTRE id -> même empreinte -> reconnu
    repost = _listing(source="bienici", id="B2", rooms=3, surface=66, rent=930,
                      city="Strasbourg", member_keys=["bienici:B2"])
    fp_l = next(t for t in toks if t.startswith("fp:"))
    assert fp_l in main._tokens(repost)


def _run():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  ok {test.__name__}")
    print(f"{len(tests)} tests OK.")


if __name__ == "__main__":
    _run()
