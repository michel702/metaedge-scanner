import requests
import time
from datetime import datetime

# ========================
# CONFIG
# ========================
POLL_SECONDS = 60
EDGE_THRESHOLD = 0.05  # 5%
MIN_VOLUME = 1000

KALSHI_URL = "https://trading-api.kalshi.com/trade-api/v2/markets"
POLYMARKET_URL = "https://gamma-api.polymarket.com/markets"

# ========================
# UTILS
# ========================
def now():
    return datetime.now().strftime("%H:%M:%S")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default


def normalize(text: str) -> str:
    return text.lower().strip()


# ========================
# FETCH KALSHI
# ========================
def fetch_kalshi():
    try:
        res = requests.get(KALSHI_URL, timeout=10)
        data = res.json()

        markets = []
        for m in data.get("markets", []):
            try:
                markets.append({
                    "ticker": m.get("ticker"),
                    "question": normalize(m.get("title", "")),
                    "price": safe_float(m.get("yes_bid", 0)) / 100,
                    "volume": safe_float(m.get("volume", 0))
                })
            except:
                continue

        return markets

    except Exception as e:
        print(f"[{now()}] Kalshi ERROR: {e}")
        return []


# ========================
# FETCH POLYMARKET
# ========================
def fetch_polymarket():
    try:
        res = requests.get(POLYMARKET_URL, timeout=10)
        data = res.json()

        markets = []
        for m in data:
            try:
                markets.append({
                    "slug": m.get("slug"),
                    "question": normalize(m.get("question", "")),
                    "price": safe_float(m.get("lastTradePrice", 0)),
                    "volume": safe_float(m.get("volume", 0))
                })
            except:
                continue

        return markets

    except Exception as e:
        print(f"[{now()}] Polymarket ERROR: {e}")
        return []


# ========================
# VALIDATION
# ========================
def is_valid_price(price):
    return 0 < price < 1


def is_valid_volume(volume):
    return volume >= MIN_VOLUME


# ========================
# MATCHING
# ========================
def is_match(q1, q2):
    words1 = set(q1.split())
    words2 = set(q2.split())

    common = words1.intersection(words2)

    return len(common) >= 3


# ========================
# EDGE DETECTION
# ========================
def find_edges(kalshi, poly):
    found = 0
    checked = 0

    for k in kalshi:
        if not is_valid_price(k["price"]) or not is_valid_volume(k["volume"]):
            continue

        for p in poly:
            if not is_valid_price(p["price"]) or not is_valid_volume(p["volume"]):
                continue

            if not is_match(k["question"], p["question"]):
                continue

            checked += 1

            edge = abs(k["price"] - p["price"])

            # 🔥 BLOQUEIO CRÍTICO: só edge real
            if edge < EDGE_THRESHOLD:
                continue

            # 🔥 LIMITADOR DE LOG
            if found < 3:
                print(f"\n🚨 EDGE FOUND 🚨")
                print(f"[{now()}] Market: {k['question'][:80]}")
                print(f"Kalshi: {k['price']:.4f} | Vol: {k['volume']:.2f}")
                print(f"Poly:   {p['price']:.4f} | Vol: {p['volume']:.2f}")
                print(f"Edge:   {edge:.4f}")
                print("-" * 60)

            found += 1

    print(f"[{now()}] Checked: {checked} | Found: {found}")

    if found == 0:
        print(f"[{now()}] Nenhuma oportunidade acima de {EDGE_THRESHOLD}")


# ========================
# MAIN LOOP
# ========================
def main():
    while True:
        try:
            print(f"\n--- scanning ---")

            kalshi = fetch_kalshi()
            poly = fetch_polymarket()

            print(f"[{now()}] Kalshi: {len(kalshi)} markets")
            print(f"[{now()}] Poly:   {len(poly)} markets")

            find_edges(kalshi, poly)

        except Exception as e:
            print(f"[{now()}] MAIN ERROR: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()