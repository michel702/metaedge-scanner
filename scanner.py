import os
import re
import json
import time
import hashlib
from datetime import datetime

import requests


# =========================
# CONFIG
# =========================
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.10"))
MIN_KALSHI_VOL = float(os.getenv("MIN_KALSHI_VOL", "1000"))
MIN_POLY_VOL = float(os.getenv("MIN_POLY_VOL", "1000"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
KALSHI_LIMIT = int(os.getenv("KALSHI_LIMIT", "1000"))
POLY_LIMIT = int(os.getenv("POLY_LIMIT", "500"))
MAX_ALERTS_PER_LOOP = int(os.getenv("MAX_ALERTS_PER_LOOP", "5"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 MetaEdgeScanner/3.0",
    "Accept": "application/json",
}

# Base pública oficial da Kalshi para market data sem auth
KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
# Gamma API pública oficial da Polymarket
POLY_URL = "https://gamma-api.polymarket.com/markets"

session = requests.Session()
session.headers.update(HEADERS)

SEEN_ALERTS = set()


# =========================
# HELPERS
# =========================
def now() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


def to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s$><.=/-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str):
    stopwords = {
        "the", "a", "an", "of", "for", "to", "in", "on", "at", "by",
        "will", "be", "is", "are", "yes", "no", "market", "markets",
        "with", "and", "or", "this", "that", "than", "from",
        "who", "what", "when", "where", "how", "if", "does", "do",
        "did", "into", "after", "before", "under", "over"
    }
    words = normalize_text(text).split()
    return [w for w in words if len(w) > 2 and w not in stopwords]


def is_valid_price(price: float) -> bool:
    # elimina 0, 1 e extremos que estavam gerando edge fake
    return price is not None and 0.05 < price < 0.95


def is_valid_volume(volume: float, min_volume: float) -> bool:
    return volume is not None and volume >= min_volume


def overlap_score(title_a: str, title_b: str) -> int:
    a_tokens = set(tokenize(title_a))
    b_tokens = set(tokenize(title_b))
    if not a_tokens or not b_tokens:
        return 0
    return len(a_tokens.intersection(b_tokens))


def titles_match(title_a: str, title_b: str) -> bool:
    """
    Matching conservador para reduzir falso positivo.
    """
    a = normalize_text(title_a)
    b = normalize_text(title_b)

    if not a or not b:
        return False

    score = overlap_score(a, b)
    if score >= 3:
        return True

    if score >= 2:
        a_first = " ".join(tokenize(a)[:4])
        b_first = " ".join(tokenize(b)[:4])
        if a_first and b_first and (a_first in b or b_first in a):
            return True

    return False


def alert_key(k_title: str, p_title: str, edge: float) -> str:
    raw = f"{k_title}|{p_title}|{round(edge, 4)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# =========================
# KALSHI
# =========================
def extract_kalshi_price(market: dict):
    """
    Tenta campos públicos mais úteis.
    Os campos em /markets costumam vir em centavos.
    """
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

        num = to_float(value, default=None)
        if num is None:
            continue

        return num / divisor

    return None


def fetch_kalshi():
    params = {
        "status": "open",
        "limit": KALSHI_LIMIT,
        "mve_filter": "exclude",  # evita combos/multivariate
    }

    try:
        res = session.get(KALSHI_URL, params=params, timeout=20)

        if res.status_code != 200:
            print(f"[{now()}] Kalshi HTTP {res.status_code}")
            print(f"[{now()}] Kalshi body preview: {res.text[:200]}")
            return []

        # evita JSONDecodeError em resposta vazia/html
        body = res.text.strip()
        if not body:
            print(f"[{now()}] Kalshi body vazio")
            return []

        try:
            data = res.json()
        except Exception:
            print(f"[{now()}] Kalshi resposta não-JSON: {body[:200]}")
            return []

        raw_markets = data.get("markets", [])
        markets = []

        for m in raw_markets:
            title = normalize_text(m.get("title", ""))
            volume = to_float(m.get("volume", 0))
            price = extract_kalshi_price(m)

            if not title:
                continue
            if not is_valid_volume(volume, MIN_KALSHI_VOL):
                continue
            if price is None or not is_valid_price(price):
                continue

            markets.append({
                "title": title,
                "yes_price": price,
                "volume": volume,
                "ticker": m.get("ticker", ""),
                "source": "kalshi",
            })

        return markets

    except Exception as e:
        print(f"[{now()}] Kalshi ERROR: {e}")
        return []


# =========================
# POLYMARKET
# =========================
def extract_poly_price(market: dict):
    """
    Primeiro tenta lastTradePrice.
    Depois tenta outcomePrices.
    """
    last_trade = market.get("lastTradePrice")
    if last_trade not in (None, ""):
        return to_float(last_trade, default=None)

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
                    return to_float(price, default=None)

            if outcome_prices:
                return to_float(outcome_prices[0], default=None)
    except Exception:
        pass

    return None


def fetch_polymarket():
    params = {
        "limit": POLY_LIMIT,
        "active": "true",
        "closed": "false",
    }

    try:
        res = session.get(POLY_URL, params=params, timeout=20)

        if res.status_code != 200:
            print(f"[{now()}] Polymarket HTTP {res.status_code}")
            print(f"[{now()}] Polymarket body preview: {res.text[:200]}")
            return []

        data = res.json()
        if not isinstance(data, list):
            print(f"[{now()}] Polymarket resposta inesperada")
            return []

        markets = []

        for m in data:
            title = normalize_text(m.get("question", ""))
            # volume vem como string na Gamma API
            volume = to_float(m.get("volume", 0))
            price = extract_poly_price(m)

            if not title:
                continue
            if not is_valid_volume(volume, MIN_POLY_VOL):
                continue
            if price is None or not is_valid_price(price):
                continue

            markets.append({
                "title": title,
                "yes_price": price,
                "volume": volume,
                "slug": m.get("slug", ""),
                "source": "polymarket",
            })

        return markets

    except Exception as e:
        print(f"[{now()}] Polymarket ERROR: {e}")
        return []


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

            # só edge positivo e acima do threshold
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