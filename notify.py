"""Notification Telegram, robuste.

send_alert(text, photo_url) : envoie une photo légendée si une image est fournie,
sinon un message texte ; retombe TOUJOURS sur le texte si la photo échoue (image
inaccessible, légende trop longue…). Renvoie True si quelque chose est parti.
Gère le rate-limit (429 + Retry-After) et les 5xx avec retries. Sans token/chat :
mode dry-run (affichage local).
"""
import os
import time

from curl_cffi import requests

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_CHAT_ID"
MAX_ATTEMPTS = 4
CAPTION_LIMIT = 1024  # limite Telegram d'une légende de photo (vs 4096 pour un texte)


def _post(method: str, payload: dict) -> bool:
    token = os.environ.get(TOKEN_ENV)
    chat_id = os.environ.get(CHAT_ENV)
    if not token or not chat_id:
        print(f"[DRY-RUN — pas de token] {method}")
        print(payload.get("text") or payload.get("caption") or "")
        print("-" * 40)
        return True

    url = f"https://api.telegram.org/bot{token}/{method}"
    payload = {"chat_id": chat_id, "parse_mode": "HTML", **payload}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(url, data=payload, timeout=25)
            if response.status_code == 200:
                return True
            if response.status_code == 429:                 # rate limit
                retry_after = 2
                try:
                    retry_after = int(response.json()["parameters"]["retry_after"])
                except Exception:
                    pass
                time.sleep(retry_after + 1)
                continue
            if 500 <= response.status_code < 600:            # transitoire
                time.sleep(2 * attempt)
                continue
            print(f"Telegram {method} {response.status_code}: {response.text[:150]}")
            return False                                     # 4xx = définitif
        except Exception as error:
            print(f"Telegram erreur réseau ({method}): {error}")
            time.sleep(2 * attempt)
    return False


def send_message(text: str) -> bool:
    return _post("sendMessage", {"text": text, "disable_web_page_preview": "true"})


def send_alert(text: str, photo_url: str | None = None) -> bool:
    """Photo légendée si possible, sinon (ou en secours) message texte."""
    if photo_url and len(text) <= CAPTION_LIMIT:
        if _post("sendPhoto", {"photo": photo_url, "caption": text}):
            return True
        # image refusée par Telegram (hotlink bloqué, format…) -> on garde l'info
    return send_message(text)
