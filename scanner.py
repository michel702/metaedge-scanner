import os
import re
import time
import json
import requests
from datetime import datetime

EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.10"))
MIN_KALSHI_VOL = float(os.getenv("MIN_KALSHI_VOL", "0"))      # debug primeiro
MIN_POLY_VOL = float(os.getenv("MIN_POLY_VOL", "0"))          # debug primeiro
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
KALSHI_LIMIT = int(os.getenv("KALSHI_LIMIT", "1000"))
POLY_LIMIT = int(os.getenv("POLY_LIMIT", "200"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 MetaEdgeScanner/1.0",
    "Accept": "application/json",
}

session = requests.Session()
session.headers.update(HEADERS)


def now():
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


def extract_kalshi_price(market: dict):
    """
    Tenta vários campos porque a resposta pode variar.
    Preferimos ask/bid em centavos ou em dólares; se não houver, tentamos last price.
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
    """
    Endpoint oficial público da Kalshi.
    """
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    params = {
        "status": "open",
        "limit": KALSHI_LIMIT,
    }

    try:
        res = session.get(url, params=params, timeout=20)
        print(f"[{now()}] Kalshi HTTP: {res.status_code}")

        if res.status_code != 200:
            print(f"[{now()}] Kalshi body preview: {res.text[:300]}")
            return []

        data = res.json()
        raw_markets = data.get("markets", [])

        print(f"[{now()}] Kalshi raw markets: {len(raw_markets)}")

        markets = []
        skipped_no_price = 0

        for m in raw_markets:
            title = normalize_text(m.get("title", ""))
            volume = to_float(m.get("volume", 0))
            price = extract_kalshi_price(m)

            if volume < MIN_KALSHI_VOL:
                continue

            if not title:
                continue

            if price is None:
                skipped_no_price += 1
                continue

            markets.append({
                "title": title,
                "yes_price": price,
                "volume": volume,
                "source": "kalshi",
                "ticker": m.get("ticker", ""),
            })

        print(f"[{now()}] Kalshi usable markets: {len(markets)} | skipped_no_price: {skipped_no_price}")
        return markets

    except Exception as e:
        print(f"[{now()}] Erro Kalshi: {e}")
        return []


def extract_poly_price(market: dict):
    """
    Primeiro tenta lastTradePrice.
    Depois tenta outcomePrices quando houver.
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
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "limit": POLY_LIMIT,
    }

    try:
        res = session.get(url, params=params, timeout=20)
        print(f"[{now()}] Polymarket HTTP: {res.status_code}")

        if res.status_code != 200:
            print(f"[{now()}] Polymarket body preview: {res.text[:300]}")
            return []

        data = res.json()
        if not isinstance(data, list):
            print(f"[{now()}] Polymarket unexpected type: {type(data)}")
            return []

        print(f"[{now()}] Polymarket raw markets: {len(data)}")

        markets = []
        skipped_no_price = 0

        for m in data:
            title = normalize_text(m.get("question", ""))
            volume = to_float(m.get("volume", 0))
            price = extract_poly_price(m)

            if volume < MIN_POLY_VOL:
                continue

            if not title:
                continue

            if price is None:
                skipped_no_price += 1
                continue

            markets.append({
                "title": title,
                "yes_price": price,
                "volume": volume,
                "source": "polymarket",
                "slug": m.get("slug", ""),
            })

        print(f"[{now()}] Polymarket usable markets: {len(markets)} | skipped_no_price: {skipped_no_price}")
        return markets

    except Exception as e:
        print(f"[{now()}] Erro Polymarket: {e}")
        return []


def titles_match(a: str, b: str) -> bool:
    if not a or not b:
        return False

    if a[:30] in b or b[:30] in a:
        return True

    a_words = [w for w in a.split() if len(w) > 4][:5]
    overlap = sum(1 for w in a_words if w in b)

    return overlap >= 2


def find_edges(kalshi_markets, poly_markets):
    found = False

    for k in kalshi_markets:
        for p in poly_markets:
            if not titles_match(k["title"], p["title"]):
                continue

            edge = p["yes_price"] - k["yes_price"]

            if abs(edge) >= EDGE_THRESHOLD:
                found = True
                print("\n🚨 EDGE FOUND 🚨")
                print(f"[{now()}] Market: {k['title'][:100]}")
                print(f"Kalshi: {k['yes_price']:.4f} | Vol: {k['volume']:.2f} | {k['ticker']}")
                print(f"Poly:   {p['yes_price']:.4f} | Vol: {p['volume']:.2f} | {p['slug']}")
                print(f"Edge:   {edge:.4f}")
                print("-" * 80)

    if not found:
        print(f"[{now()}] Nenhuma oportunidade acima de {EDGE_THRESHOLD}")


def main():
    while True:
        try:
            print("\n--- scanning ---")
            kalshi = fetch_kalshi()
            poly = fetch_polymarket()

            print(f"[{now()}] Kalshi markets: {len(kalshi)}")
            print(f"[{now()}] Polymarket markets: {len(poly)}")

            find_edges(kalshi, poly)

        except Exception as e:
            print(f"[{now()}] MAIN ERROR: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()