import requests
import time
import os

EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.10"))
MIN_KALSHI_VOL = float(os.getenv("MIN_KALSHI_VOL", "0"))      # debug: deixa 0 por enquanto
MIN_POLY_VOL = float(os.getenv("MIN_POLY_VOL", "0"))          # debug: deixa 0 por enquanto
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))


def to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def fetch_kalshi():
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"

    try:
        res = requests.get(url, timeout=15)
        data = res.json()

        markets = []

        for m in data.get("markets", []):
            volume = to_float(m.get("volume", 0))
            yes_price = m.get("yes_ask", None)

            if yes_price is None:
                continue

            yes_price = to_float(yes_price) / 100.0

            if volume < MIN_KALSHI_VOL:
                continue

            markets.append({
                "title": str(m.get("title", "")).lower(),
                "yes_price": yes_price,
                "volume": volume
            })

        return markets

    except Exception as e:
        print("Erro Kalshi:", e)
        return []


def fetch_polymarket():
    url = "https://gamma-api.polymarket.com/markets"

    try:
        res = requests.get(url, timeout=15)
        data = res.json()

        markets = []

        for m in data:
            volume = to_float(m.get("volume", 0))
            price = m.get("lastTradePrice", None)

            if price is None:
                continue

            price = to_float(price)

            if volume < MIN_POLY_VOL:
                continue

            markets.append({
                "title": str(m.get("question", "")).lower(),
                "yes_price": price,
                "volume": volume
            })

        return markets

    except Exception as e:
        print("Erro Polymarket:", e)
        return []


def titles_match(k_title, p_title):
    k = k_title.strip()
    p = p_title.strip()

    if not k or not p:
        return False

    # matching simples para MVP
    return (
        k[:25] in p
        or p[:25] in k
        or any(word in p for word in k.split()[:4] if len(word) > 4)
    )


def find_edges(kalshi, poly):
    found = False

    for k in kalshi:
        for p in poly:
            if not titles_match(k["title"], p["title"]):
                continue

            edge = p["yes_price"] - k["yes_price"]

            if abs(edge) >= EDGE_THRESHOLD:
                found = True
                print("\n🚨 EDGE FOUND 🚨")
                print("Market:", k["title"][:100])
                print("Kalshi:", round(k["yes_price"], 4), "| Vol:", round(k["volume"], 2))
                print("Poly:", round(p["yes_price"], 4), "| Vol:", round(p["volume"], 2))
                print("Edge:", round(edge, 4))
                print("-" * 80)

    if not found:
        print(f"Nenhuma oportunidade acima de {EDGE_THRESHOLD}")


while True:
    print("\n--- scanning ---")

    kalshi = fetch_kalshi()
    poly = fetch_polymarket()

    print("Kalshi markets:", len(kalshi))
    print("Polymarket markets:", len(poly))

    find_edges(kalshi, poly)

    time.sleep(POLL_SECONDS)