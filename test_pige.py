"""Tests de non-régression. Lancer : `python test_pige.py` (sans réseau)."""
import main
from models import Listing


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
    out = main.format_alert(_listing(title="T3 <x> & co", profiles=["coloc"],
                                     url="https://x/a?b=1&c=2"))
    assert "<x>" not in out and "&lt;x&gt;" in out and "&amp;" in out


def _run():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  ok {test.__name__}")
    print(f"{len(tests)} tests OK.")


if __name__ == "__main__":
    _run()
