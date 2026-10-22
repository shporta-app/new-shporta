"""Export the compact, read-only DB the API serves, as seed/phia-api.db.gz (committed; the server unpacks it).

    python build_seed.py

It holds only what the API needs: current products with their match key and size, the match groups and the shops.
The full data/phia.db (price history, raw categories) stays on the machine that scrapes.
"""
import gzip
import shutil
import sqlite3
from pathlib import Path

from match import parse

HERE = Path(__file__).parent
SRC = HERE / "data" / "phia.db"
OUT = HERE / "seed" / "phia-api.db"


def main():
    OUT.parent.mkdir(exist_ok=True)
    OUT.unlink(missing_ok=True)
    src = sqlite3.connect(SRC, timeout=120)
    dst = sqlite3.connect(OUT)
    dst.executescript("""
        CREATE TABLE products (id INTEGER PRIMARY KEY, shop TEXT, title TEXT, brand TEXT, url TEXT, image TEXT,
                               price REAL, regular_price REAL, currency TEXT, in_stock INTEGER,
                               name_key TEXT, size_val REAL, size_unit TEXT);
        CREATE TABLE matches (product_id INTEGER PRIMARY KEY, group_id TEXT);
        CREATE TABLE shops (domain TEXT PRIMARY KEY, category TEXT, products INTEGER);
        CREATE VIRTUAL TABLE words USING fts5(name_key, content='products', content_rowid='id', tokenize='unicode61');
    """)
    rows = []
    for r in src.execute("""SELECT id, shop, title, brand, url, image, price, regular_price, currency, in_stock
                            FROM products WHERE price > 0"""):
        key, size = parse(r[2])
        rows.append((*r, key, size[0] if size else None, size[1] if size else None))
    dst.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    dst.executemany("INSERT INTO matches VALUES (?,?)", src.execute("SELECT product_id, group_id FROM matches"))
    dst.executemany("INSERT INTO shops VALUES (?,?,?)",
                    src.execute("SELECT domain, category, products FROM shops WHERE status IN ('ok','error')"))
    dst.executescript("""
        CREATE INDEX products_key ON products(name_key);
        CREATE INDEX matches_group ON matches(group_id);
        INSERT INTO words(words) VALUES('rebuild');
    """)
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    with open(OUT, "rb") as f, gzip.open(str(OUT) + ".gz", "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    print(f"{len(rows):,} products -> {OUT.stat().st_size / 1e6:.0f} MB, gzipped {Path(str(OUT) + '.gz').stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
