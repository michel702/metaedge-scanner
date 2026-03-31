import os
import re
import json
import time
import hashlib
from datetime import datetime, UTC
from difflib import SequenceMatcher

import requests


# =========================
# CONFIG
# =========================
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.10"))
MIN_KALSHI_VOL = float(os.getenv("MIN_KALSHI_VOL", "0"))
MIN_POLY_VOL = float(os.getenv("MIN_POLY_VOL", "1000"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
KALSHI_LIMIT = int(os.getenv("KALSHI_LIMIT", "1000"))
POLY_LIMIT = int(os.getenv("POLY_LIMIT", "500"))
MAX_ALERTS_PER_LOOP = int(os.getenv("MAX_ALERTS_PER_LOOP", "5"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 MetaEdgeScanner/7.0",
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
def now() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def to_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def normalize_text(text: str) -> str:
    text = (text or "").lower().strip()

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

    text = re.sub(r"[^a-z0-9\s$><.=/-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str):
    stopwords = {
        "the", "a", "an", "of", "for", "to", "in", "on", "at", "by",
        "will", "be", "is", "are", "yes", "no", "market", "markets",
        "with", "and", "or", "this", "that", "than", "from",
        "who", "what", "when", "where", "how", "if", "does", "do",
        "did", "into", "after", "before", "under", "over",
        "which", "party", "control", "price", "point", "points",
        "score", "scored", "wins", "win"
    }
    words = normalize_text(text).split()
    return [w for w in words if len(w) > 2 and w not in stopwords]


def is_valid_price(price: float) -> bool:
    return price is not None and 0.01 < price < 0.99


def is_valid_volume(volume: float, min_volume: float) -> bool:
    return volume is not None and volume >= min_volume


def alert_key(k_title: str, p_title: str, edge: float) -> str:
    raw = f"{k_title}|{p_title}|{round(edge, 4)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def safe_get_json(url, params=None):
    try:
        res = session.get(url, params=params, timeout=20)

        if res.status_code != 200:
            print(f"[{now()}] HTTP ERROR {res.status_code} -> {url}")
            print(f"[{now()}] BODY PREVIEW: {res.text[:200]}")
            return None

        body = res.text.strip()
        if not body:
            print(f"[{now()}] EMPTY BODY -> {url}")
            return None

        try:
            return res.json()
        except Exception:
            print(f"[{now()}] NON-JSON BODY -> {url}")
            print(f"[{now()}] BODY PREVIEW: {body[:200]}")
            return None

    except Exception as e:
        print(f"[{now()}] REQUEST ERROR -> {url} -> {e}")
        return None


# =========================
# MATCHING
# =========================
def titles_match(title_a: str, title_b: str) -> bool:
    a_norm = normalize_text(title_a)
    b_norm = normalize_text(title_b)

    a_tokens = set(tokenize(a_norm))
    b_tokens = set(tokenize(b_norm))

    if not a_tokens or not b_tokens:
        return False

    common = a_tokens.intersection(b_tokens)

    # match forte
    if len(common) >= 2:
        return True

    important_words = {
        "trump", "biden", "democrats", "republicans", "senate", "house",
        "fed", "rates", "inflation", "cpi", "bitcoin", "ethereum",
        "solana", "tesla", "apple", "spacex", "putin", "zelensky",
        "lula", "bolsonaro", "election", "elections", "president",
        "btc", "eth"
    }

    if any(word in a_tokens and word in b_tokens for word in important_words):
        return True

    # similaridade textual como fallback
    ratio = SequenceMatcher(None, a_norm, b_norm).ratio()
    if ratio >= 0.62:
        return True

    # fallback leve
    if len(common) >= 1 and (len(a_tokens) + len(b_tokens)) < 10:
        return True

    return False


# =========================
# KALSHI
# =========================
def extract_kalshi_price(market: dict):
    candidates = [
        ("yes_ask", 100.0),
        ("yes_bid", 100.0),
        ("last_price", 100.0),
        ("yes_ask_dollars", 1.0),
        ("yes_bid_dollars", 1.0),
        ("last_price_dollars", 1.0),
    ]

    for key, divisor in candidates:
        value = market.get(key)
        if value is None or value == "":
            continue

        num = to_float(value)
        if num is None:
            continue

        return num / divisor

    return None


def fetch_kalshi():
    params = {
        "status": "open",
        "limit": KALSHI_LIMIT,
        "mve_filter": "exclude",
    }

    data = safe_get_json(KALSHI_URL, params=params)
    if not data:
        print(f"[{now()}] Kalshi raw=0 usable=0 skipped_volume=0 skipped_price=0")
        return []

    raw_markets = data.get("markets", [])
    markets = []

    skipped_volume = 0
    skipped_price = 0

    for m in raw_markets:
        title = normalize_text(m.get("title", ""))
        volume = to_float(m.get("volume", 0), 0.0)
        price = extract_kalshi_price(m)

        if not title:
            continue

        if not is_valid_volume(volume, MIN_KALSHI_VOL):
            skipped_volume += 1
            continue

        if not is_valid_price(price):
            skipped_price += 1
            continue

        markets.append({
            "title": title,
            "yes_price": price,
            "volume": volume,
            "ticker": m.get("ticker", ""),
        })

    print(
        f"[{now()}] Kalshi raw={len(raw_markets)} usable={len(markets)} "
        f"skipped_volume={skipped_volume} skipped_price={skipped_price}"
    )
    return markets


# =========================
# POLYMARKET
# =========================
def extract_poly_price(market: dict):
    last_trade = market.get("lastTradePrice")
    if last_trade not in (None, ""):
        return to_float(last_trade)

    outcomes = market.get("outcomes")
    outcome_prices = market.get("outcomePrices")

    try:
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)

        if isinstance(outcomes, list) and isinstance(outcome_prices, list):
            for outcome, price in zip(outcomes, outcome_prices):
                if str(outcome).strip().lower() == "yes":
                    return to_float(price)

            if outcome_prices:
                return to_float(outcome_prices[0])
    except Exception:
        pass

    return None


def fetch_polymarket():
    params = {
        "limit": POLY_LIMIT,
        "active": "true",
        "closed": "false",
    }

    data = safe_get_json(POLY_URL, params=params)
    if not data or not isinstance(data, list):
        print(f"[{now()}] Poly raw=0 usable=0 skipped_volume=0 skipped_price=0")
        return []

    markets = []

    skipped_volume = 0
    skipped_price = 0

    for m in data:
        title = normalize_text(m.get("question", ""))
        volume = to_float(m.get("volume", 0), 0.0)
        price = extract_poly_price(m)

        if not title:
            continue

        if not is_valid_volume(volume, MIN_POLY_VOL):
            skipped_volume += 1
            continue

        if not is_valid_price(price):
            skipped_price += 1
            continue

        markets.append({
            "title": title,
            "yes_price": price,
            "volume": volume,
            "slug": m.get("slug", ""),
        })

    print(
        f"[{now()}] Poly raw={len(data)} usable={len(markets)} "
        f"skipped_volume={skipped_volume} skipped_price={skipped_price}"
    )
    return markets


# =========================
# EDGE DETECTION
# =========================
def find_edges(kalshi_markets, poly_markets):
    found = 0
    checked_pairs = 0
    matched_pairs = 0

    for k in kalshi_markets:
        for p in poly_markets:
            checked_pairs += 1

            if not titles_match(k["title"], p["title"]):
                continue

            matched_pairs += 1
            edge = p["yes_price"] - k["yes_price"]

            if edge < EDGE_THRESHOLD:
                continue

            key = alert_key(k["title"], p["title"], edge)
            if key in SEEN_ALERTS:
                continue

            SEEN_ALERTS.add(key)
            found += 1

            if found <= MAX_ALERTS_PER_LOOP:
                print("\n🚨 EDGE FOUND")
                print(f"[{now()}] Market: {k['title'][:120]}")
                print(f"Kalshi: {k['yes_price']:.4f} | Vol: {k['volume']:.2f} | {k['ticker']}")
                print(f"Poly:   {p['yes_price']:.4f} | Vol: {p['volume']:.2f} | {p['slug']}")
                print(f"Edge:   {edge:.4f}")

    print(
        f"[{now()}] Kalshi={len(kalshi_markets)} | "
        f"Poly={len(poly_markets)} | "
        f"Checked={checked_pairs} | "
        f"Matched={matched_pairs} | "
        f"Alerts={found}"
    )

    if found == 0:
        print(f"[{now()}] Nenhuma oportunidade REAL acima de {EDGE_THRESHOLD}")


# =========================
# MAIN LOOP
# =========================
def main():
    while True:
        try:
            kalshi = fetch_kalshi()
            poly = fetch_polymarket()
            find_edges(kalshi, poly)
        except Exception as e:
            print(f"[{now()}] MAIN ERROR: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()