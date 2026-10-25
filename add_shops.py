"""Add the shops a vetting pass approved (shops_new_vetted.json, verdict "ok") with a first full collection.

    python add_shops.py              # every approved shop not in the database yet, one at a time
    python add_shops.py gotech.al    # only these

Each shop goes through scrape.run: robots.txt and its Crawl-delay are obeyed, and a 403/429/challenge stops that
shop for good (status "blocked"). From the next night on, refresh.py keeps it up to date like every other shop.
"""
import json
import sqlite3
import sys
from pathlib import Path

import scrape

HERE = Path(__file__).parent


def main():
    vetted = [s for s in json.loads((HERE / "shops_new_vetted.json").read_text(encoding="utf-8")) if s["verdict"] == "ok"]
    known = {r[0] for r in sqlite3.connect(HERE / "data" / "phia.db").execute("SELECT domain FROM shops")}
    only = set(sys.argv[1:])
    todo = [s for s in vetted if (s["domain"] in only if only else s["domain"] not in known)]
    todo.sort(key=lambda s: s.get("products_estimate") or 0)  # small shops first: results show up sooner
    print(f"adding {len(todo)} shops: {', '.join(s['domain'] for s in todo)}", flush=True)
    for s in todo:
        scrape.run(s["domain"], s["category"])


if __name__ == "__main__":
    main()
