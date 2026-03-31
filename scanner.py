import requests
import time
import os

EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", 0.10))
MIN_KALSHI_VOL = int(os.getenv("MIN_KALSHI_VOL", 100000))
MIN_POLY_VOL = int(os.getenv("MIN_POLY_VOL", 100000))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", 30))


def fetch_kalshi():
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"

    try:
        res = requests.get(url)
        data = res.json()

        markets = []

        for m in data.get("markets", []):
            volume = m.get("volume", 0)

            if volume < MIN_KALSHI_VOL:
                continue

            yes_price = m.get("yes_ask", None)

            if yes_price is None:
                continue

            markets.append({
                "title": m.get("title", "").lower(),
                "yes_price": yes_price / 100,
                "volume": volume
            })

        return markets

    except Exception as e:
        print("Erro Kalshi:", e)
        return []


def fetch_polymarket():
    url = "https://gamma-api.polymarket.com/markets"

    try:
        res = requests.get(url)
        data = res.json()

        markets = []

        for m in data:
            volume = m.get("volume", 0)

            if volume < MIN_POLY_VOL:
                continue

            price = m.get("lastTradePrice", None)

            if price is None:
                continue

            markets.append({
                "title": m.get("question", "").lower(),
                "yes_price": float(price),
                "volume": volume
            })

        return markets

    except Exception as e:
        print("Erro Polymarket:", e)
        return []


def find_edges(kalshi, poly):
    found = False

    for k in kalshi:
        for p in poly:
            # matching simples (melhoraremos depois)
            if k["title"][:30] in p["title"] or p["title"][:30] in k["title"]:

                edge = p["yes_price"] - k["yes_price"]

                if abs(edge) > EDGE_THRESHOLD:
                    found = True

                    print("\n🚨 EDGE FOUND 🚨")
                    print("Market:", k["title"][:80])
                    print("Kalshi:", round(k["yes_price"], 3))
                    print("Poly:", round(p["yes_price"], 3))
                    print("Edge:", round(edge, 3))

    if not found:
        print("Nenhuma oportunidade acima de", EDGE_THRESHOLD)


while True:
    print("\n--- scanning ---")

    kalshi = fetch_kalshi()
    poly = fetch_polymarket()

    print("Kalshi markets:", len(kalshi))
    print("Polymarket markets:", len(poly))

    find_edges(kalshi, poly)

    time.sleep(POLL_SECONDS)