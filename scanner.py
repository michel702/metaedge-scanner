import os
import time
import requests
from datetime import datetime

EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.10"))
MIN_KALSHI_VOL = float(os.getenv("MIN_KALSHI_VOL", "100000"))
MIN_POLY_VOL = float(os.getenv("MIN_POLY_VOL", "500000"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))


def now():
    return datetime.utcnow().strftime("%H:%M:%S")


def get_kalshi():
    try:
        url = "https://api.elections.kalshi.com/trade-api/v2/markets?status=open"
        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            print(f"Kalshi HTTP {r.status_code}")
            return []

        data = r.json()
        markets = []

        for m in data.get("markets", []):
            prob = m.get("yes_ask")
            vol = m.get("volume", 0)

            if prob is None:
                continue

            prob = prob / 100 if prob > 1 else prob

            markets.append({
                "title": m.get("title", ""),
                "prob": prob,
                "volume": vol
            })

        return markets

    except Exception as e:
        print(f"Kalshi error: {e}")
        return []


def get_poly():
    try:
        url = "https://gamma-api.polymarket.com/markets?active=true"
        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            print(f"Polymarket HTTP {r.status_code}")
            return []

        data = r.json()
        markets = []

        for m in data:
            prob = m.get("lastTradePrice")
            vol = m.get("volume", 0)

            if prob is None:
                continue

            prob = float(prob)
            prob = prob / 100 if prob > 1 else prob

            markets.append({
                "title": m.get("question", ""),
                "prob": prob,
                "volume": vol
            })

        return markets

    except Exception as e:
        print(f"Polymarket error: {e}")
        return []


def is_possible_match(k_title, p_title):
    k_words = k_title.lower().split()
    p_title_lower = p_title.lower()

    # matching bem simples pro MVP
    for word in k_words[:3]:
        if len(word) > 3 and word in p_title_lower:
            return True

    return False


def compare(kalshi, poly):
    found = False

    for k in kalshi:
        for p in poly:
            if k["volume"] < MIN_KALSHI_VOL:
                continue

            if p["volume"] < MIN_POLY_VOL:
                continue

            if not is_possible_match(k["title"], p["title"]):
                continue

            edge = abs(k["prob"] - p["prob"])

            if edge >= EDGE_THRESHOLD:
                found = True
                print("\n🚨 OPORTUNIDADE 🚨")
                print(f"[{now()}] EDGE: {round(edge * 100, 2)}%")
                print(f"Kalshi: {round(k['prob'] * 100, 2)}% | Vol: {k['volume']} | {k['title']}")
                print(f"Poly:   {round(p['prob'] * 100, 2)}% | Vol: {p['volume']} | {p['title']}")
                print("-" * 80)

    if not found:
        print(f"[{now()}] Nenhuma oportunidade acima de {EDGE_THRESHOLD * 100:.0f}%")


def main():
    while True:
        try:
            print(f"\n[{now()}] scanning...")

            kalshi = get_kalshi()
            poly = get_poly()

            print(f"[{now()}] Kalshi markets: {len(kalshi)}")
            print(f"[{now()}] Polymarket markets: {len(poly)}")

            compare(kalshi, poly)

        except Exception as e:
            print(f"MAIN ERROR: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()