"""Client HTTP partagé par toutes les sources.

Une seule définition de la session (impersonation TLS Chrome pour passer les
protections passives) et des retries réseau — au lieu de les réécrire dans
chaque scraper.
"""
import time

from curl_cffi import requests

DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
BACKOFF_SECONDS = 2


def make_session() -> "requests.Session":
    return requests.Session(impersonate="chrome")


def get(session, url: str, *, params=None, headers=None,
        timeout: int = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES):
    """GET avec retries sur erreur réseau (pas sur les codes HTTP : l'appelant
    décide quoi faire d'un 403/404)."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return session.get(url, params=params, headers=headers, timeout=timeout)
        except Exception as error:
            last_error = error
            if attempt < retries:
                time.sleep(BACKOFF_SECONDS * attempt)
    raise last_error
