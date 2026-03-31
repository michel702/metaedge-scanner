import os
import re
import json
import time
import hashlib
from datetime import datetime, UTC

import requests


# =========================
# CONFIG
# =========================
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.10"))
MIN_KALSHI_VOL = float(os.getenv("MIN_KALSHI_VOL", "0"))
MIN_POLY_VOL = float(os.getenv("MIN_POLY_VOL", "1000"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 MetaEdgeScanner/EV",
    "Accept": "application/json",
}

KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
POLY_URL = "https://gamma-api.polymarket.com/markets"

session = requests.Session()
session.headers.update(HEADERS)

SEEN_ALERTS = set()


# =========================
# HELPERS
# =========================
def now():
    return datetime.now(UTC).strftime("%H:%M:%S")


def to_float(x):
    try:
        return float(x)
    except:
        return None


# 🔥 NORMALIZAÇÃO AGRESSIVA
def normalize(text):
    text = text.lower()

    # sinônimos chave (isso aumenta MUITO match)
    replacements = {
        "interest rates": "rates",
        "raise rates": "rates up",
        "increase rates": "rates up",
        "cut rates": "rates down",
        "decrease rates": "rates down",
        "presidential election": "election",
        "president": "election",
        "btc": "bitcoin",
        "eth": "ethereum",
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def tokens(text):
    return set(normalize(text).split())


# 🔥 MATCHING MAIS AGRESSIVO (CORE DO GANHO DE EV)
def is_match(a, b):
    ta = tokens(a)
    tb = tokens(b)

    if not ta or not tb:
        return False

    common = ta & tb

    # regra 1: match normal
    if len(common) >= 2:
        return True

    # regra 2: fuzzy leve
    score = len(common) / max(len(ta), len(tb))

    if score > 0.3:
        return True

    return False


def alert_key(a, b):
    return hashlib.md5(f"{a}|{b}".encode()).hexdigest()


# =========================
# FETCH KALSHI
# =========================
def fetch_kalshi():
    res = session.get(KALSHI_URL, params={"limit": 1000})

    data = res.json()
    markets = []

    for m in data.get("markets", []):
        title = m.get("title", "")
        volume = to_float(m.get("volume", 0))

        price = None
        if m.get("yes_ask"):
            price = to_float(m["yes_ask"]) / 100

        if not price or not (0.01 < price < 0.99):
            continue

        markets.append({
            "title": title,
            "price": price,
            "volume": volume
        })

    return markets


# =========================
# FETCH POLY
# =========================
def fetch_poly():
    res = session.get(POLY_URL, params={"limit": 500})
    data = res.json()

    markets = []

    for m in data:
        title = m.get("question", "")
        volume = to_float(m.get("volume", 0))

        price = None
        if m.get("lastTradePrice"):
            price = to_float(m["lastTradePrice"])

        if not price or not (0.01 < price < 0.99):
            continue

        markets.append({
            "title": title,
            "price": price,
            "volume": volume
        })

    return markets


# =========================
# EDGE
# =========================
def scan(kalshi, poly):
    checked = 0
    matched = 0
    found = 0

    for k in kalshi:
        for p in poly:
            checked += 1

            if not is_match(k["title"], p["title"]):
                continue

            matched += 1

            edge = p["price"] - k["price"]

            if edge < EDGE_THRESHOLD:
                continue

            key = alert_key(k["title"], p["title"])
            if key in SEEN_ALERTS:
                continue

            SEEN_ALERTS.add(key)
            found += 1

            print("\n🚨 EDGE FOUND")
            print(k["title"])
            print(p["title"])
            print(f"Kalshi: {k['price']:.3f}")
            print(f"Poly:   {p['price']:.3f}")
            print(f"Edge:   {edge:.3f}")

    print(f"[{now()}] Checked={checked} Matched={matched} Alerts={found}")


# =========================
# LOOP
# =========================
def main():
    while True:
        try:
            k = fetch_kalshi()
            p = fetch_poly()

            scan(k, p)

        except Exception as e:
            print("ERROR:", e)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()