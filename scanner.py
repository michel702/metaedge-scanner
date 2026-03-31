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
        r = requests.get("https://api.elections.kalshi.com/trade-api/v2/markets?status=open")
        data = r.json()
        markets = []
        for m in data.get("markets", []):
            prob = m.get("yes_ask")
            vol = m.get("volume", 0)
            if prob:
                prob = prob / 100 if prob > 1 else prob
                markets.append({
                    "title": m.get("title", ""),
                    "prob": prob,
                    "volume": vol
                })
        return markets
    except:
        return []

def get_poly():
    try:
        r = requests.get("https://gamma-api.polymarket.com/markets?active=true")
        data = r.json()
        markets = []
        for m in data:
            prob = m.get("lastTradePrice")
            vol = m.get("volume", 0)
            if prob:
                prob = prob / 100 if prob > 1 else prob
                markets.append({
                    "title": m.get("question", ""),
                    "prob": prob,
                    "volume": vol
                })
        return markets
    except:
        return []

def compare(kalshi, poly):
    for k in kalshi:
        for p in poly:
            if k["volume"] < MIN_KALSHI_VOL or p["volume"] < MIN_POLY_VOL:
                continue

            if any(word in k["title"].lower() for word in p["title"].lower().split()[:3]):
                edge = abs(k["prob"] - p["prob"])

                if edge >= EDGE_THRESHOLD:
                    print("\n🚨 OPORTUNIDADE 🚨")
                    print(f"[{now()}] EDGE: {round(edge*100,2)}%")
                    print(f"Kalshi: {round(k['prob']*100,2)}% | {k['title']}")
                    print(f"Poly:   {round(p['prob']*100,2)}% | {p['title']}")

def main():
    while True:
        kalshi = get_kalshi()
        poly = get_poly()

        print(f"[{now()}] scanning...")

        compare(kalshi, poly)

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()