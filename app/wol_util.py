# app/wol_util.py

import os
import socket
import struct
import time
from typing import Optional

import requests


def wake_on_lan(
    mac_address: str,
    broadcast_ip: str = "255.255.255.255",
    port: int = 9,
) -> None:
    """
    Réveille le PC fixe.

    1) Si les variables d'environnement suivantes sont définies :
       - URL_HAY_PUBLIQUE
       - PREDICAT_WEBHOOK
       - WEBHOOK_WAKE_PCFIXE

       → envoie d'abord une requête HTTP GET vers le webhook Home Assistant
         pour déléguer le WOL au HAY (utile en remote).

    2) Si ces variables ne sont pas définies, ou en cas d'erreur d'appel,
       → fallback : envoi classique du paquet magique WOL sur le réseau local
         avec la MAC fournie, le broadcast_ip et le port indiqués.
    """

    # ─────────────────────────────────────────────────────────────
    # 1) Tentative via Home Assistant (webhook)
    # ─────────────────────────────────────────────────────────────
    url_publique = (os.getenv("URL_HAY_PUBLIQUE") or "").rstrip("/")
    predicat = os.getenv("PREDICAT_WEBHOOK") or ""
    webhook_id = os.getenv("WEBHOOK_WAKE_PCFIXE") or ""

    if url_publique and predicat and webhook_id:
        webhook_url = f"{url_publique}{predicat}{webhook_id}"
        try:
            resp = requests.get(webhook_url, timeout=5)
            resp.raise_for_status()
            print(f"[WOL] Webhook Home Assistant appelé : {webhook_url} (status {resp.status_code})")
            return
        except Exception as e:
            # On log l'erreur, puis on retombe en mode paquet magique local
            print(f"[WOL] Erreur appel webhook Home Assistant : {e} – fallback paquet magique local")

    # ─────────────────────────────────────────────────────────────
    # 2) Fallback : paquet magique WOL classique (LAN)
    # ─────────────────────────────────────────────────────────────
    mac = mac_address.replace(":", "").replace("-", "").lower()
    if len(mac) != 12 or any(c not in "0123456789abcdef" for c in mac):
        raise ValueError(f"Adresse MAC invalide pour WOL : {mac_address}")

    # FF FF FF FF FF FF + 16 fois l'adresse MAC
    data = bytes.fromhex("ff" * 6 + mac * 16)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(data, (broadcast_ip, port))

    print(f"[WOL] Paquet magique envoyé vers {broadcast_ip}:{port} pour {mac_address}")


def is_server_up(
    base_url: str,
    ping_path: str = "/ping",
    timeout: float = 2.0,
) -> bool:
    """
    Vérifie si le serveur LLM local répond sur /ping (ou autre chemin).
    Retourne True si HTTP 200, False sinon.
    """
    url = base_url.rstrip("/") + ping_path
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def wait_for_server(
    base_url: str,
    ping_path: str = "/ping",
    max_wait_sec: int = 90,
    poll_interval_sec: int = 3,
    timeout_single: float = 2.0,
) -> bool:
    """
    Boucle d'attente : ping régulièrement le serveur LLM jusqu'à max_wait_sec.
    Retourne True si le serveur répond, False sinon.
    """
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        if is_server_up(base_url, ping_path=ping_path, timeout=timeout_single):
            return True
        time.sleep(poll_interval_sec)
    return False
