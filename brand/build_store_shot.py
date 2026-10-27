"""Builds dist/store/screenshot-1.png (1280x800) for the extension stores: the real panel with today's real prices.
Run: python brand/build_store_shot.py   (needs internet for /api/lookup)
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_brand import CHROME, ROOT, tile  # noqa: E402

SHOP, PRICE = "pinkpharm.al", 1320
TITLE = "CeraVe Moisturizing Cream 177ml"
HIDE = {"beautene.al"}  # shops we don't show in store pictures


def main():
    req = urllib.request.Request("https://shporta.app/api/lookup", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"title": TITLE, "price": PRICE, "currency": "ALL", "url": f"https://{SHOP}/x"}).encode())
    data = json.load(urllib.request.urlopen(req, timeout=30))
    data["exact"] = [o for o in data["exact"] if o["shop"] not in HIDE]
    data["same_name"] = []  # keeps the picture to the main thing: the same product, shop by shop
    page = (ROOT / "brand" / "store-shot.html").read_text(encoding="utf-8")
    page = (page.replace("{MARK}", tile()).replace("{DATA}", json.dumps(data))
                .replace("{SHOP}", SHOP).replace("{PRICE}", str(PRICE)))
    tmp = ROOT / "brand" / "_store-shot.html"
    tmp.write_text(page, encoding="utf-8")
    out = ROOT / "dist" / "store"
    out.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "http.server", "8812", "--bind", "127.0.0.1"], cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1280,800",
                        "--virtual-time-budget=5000", f"--screenshot={out / 'screenshot-1.png'}",
                        "http://127.0.0.1:8812/brand/_store-shot.html"], check=True, capture_output=True)
    finally:
        server.terminate()
        tmp.unlink()
    print(out / "screenshot-1.png")


if __name__ == "__main__":
    main()
