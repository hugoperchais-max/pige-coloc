"""Notification Telegram, robuste.

send_message renvoie True si envoyé (ou en dry-run), False si échec définitif.
Gère le rate-limit (429 + Retry-After) et les erreurs serveur (5xx) avec retries.
Sans token/chat configurés : mode dry-run (affichage local), utile pour tester.
"""
import os
import time

from curl_cffi import requests

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_CHAT_ID"
MAX_ATTEMPTS = 4


def send_message(text: str) -> bool:
    token = os.environ.get(TOKEN_ENV)
    chat_id = os.environ.get(CHAT_ENV)

    if not token or not chat_id:
        print("[DRY-RUN — pas de token Telegram]")
        print(text)
        print("-" * 40)
        return True

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": "true"}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(url, data=payload, timeout=20)
            if response.status_code == 200:
                return True
            if response.status_code == 429:  # rate limit
                retry_after = 2
                try:
                    retry_after = int(response.json()["parameters"]["retry_after"])
                except Exception:
                    pass
                time.sleep(retry_after + 1)
                continue
            if 500 <= response.status_code < 600:  # erreur serveur transitoire
                time.sleep(2 * attempt)
                continue
            print(f"Telegram {response.status_code}: {response.text[:150]}")
            return False  # 4xx (hors 429) = erreur définitive (mauvais token/chat)
        except Exception as error:
            print(f"Telegram erreur réseau: {error}")
            time.sleep(2 * attempt)

    return False
