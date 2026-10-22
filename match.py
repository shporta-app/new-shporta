"""Group the same product across shops.

    python match.py            -> fills the `matches` table (product_id -> group_id)

How a product is identified:
  name key  = the set of meaningful words in the title (accents folded, punctuation dropped, size removed),
              so "Dr.Althea – 345 Relief Cream" == "DR. ALTHEA 345 Relief Cream" == "Dr. Althea 345 Relief Cream - 50"
  size      = "50ml", or a bare "- 50" suffix (Shopify variant titles), or unknown

Two rows are the same product when the name keys are equal and the sizes don't contradict each other. A row with
an unknown size joins the group only when that name has exactly one known size; otherwise it stays alone, because
we can't tell which size it is. Different words (cream vs cream mist vs cream mask) never match.
Precision over recall: a wrong match shows a false "cheaper elsewhere", which is worse than a missed one.
"""
import collections
import hashlib
import re
import sqlite3
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent

STOP = {
    "the", "and", "for", "with", "of", "de", "la", "le", "di", "per", "me", "dhe", "e", "i", "te", "ne", "nga",
    "a", "an", "in", "on", "by", "x", "new", "ri", "set", "pcs", "cope",
}
UNIT = {"ml": "ml", "l": "l", "lt": "l", "g": "g", "gr": "g", "gram": "g", "kg": "kg", "oz": "oz", "fl": "oz",
        "caps": "caps", "kapsula": "caps", "tab": "tab", "tableta": "tab"}
SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|lt|l|gr|gram|g|kg|fl\.?\s*oz|oz|caps|kapsula|tableta|tab)\b")
BARE_SIZE_RE = re.compile(r"\s[-–]\s*(\d{1,4})\s*$")  # "Cream - 50" (variant title without a unit)


def fold(s):
    s = unicodedata.normalize("NFKD", s.lower().replace(" ", " ").replace("\xa0", " "))
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def parse(title):
    t = fold(title)
    size = None
    m = SIZE_RE.search(t)
    if m:
        u = m.group(2)
        size = (float(m.group(1).replace(",", ".")), "oz" if "oz" in u else UNIT.get(u, u))
        t = t[: m.start()] + " " + t[m.end():]
    else:
        b = BARE_SIZE_RE.search(t)
        if b:
            size = (float(b.group(1)), None)
            t = t[: b.start()]
    words = {w for w in re.findall(r"[a-z0-9%]+", t) if w not in STOP and not (len(w) == 1 and not w.isdigit())}
    return " ".join(sorted(words)), size


def same_size(a, b):
    return a[0] == b[0] and (a[1] is None or b[1] is None or a[1] == b[1])


def main():
    con = sqlite3.connect(HERE / "data" / "phia.db", timeout=120)
    con.execute("CREATE TABLE IF NOT EXISTS matches (product_id INTEGER PRIMARY KEY, group_id TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS matches_group ON matches(group_id)")

    by_name = collections.defaultdict(list)
    for pid, shop, title in con.execute("SELECT id, shop, title FROM products WHERE price > 0"):
        key, size = parse(title)
        if len(key.split()) >= 2:  # one word ("Bluza") is too vague to match on
            by_name[key].append((pid, shop, size))

    rows = []
    for key, items in by_name.items():
        if len({shop for _, shop, _ in items}) < 2:
            continue
        sizes = []
        for _, _, s in items:
            if s and not any(same_size(s, x) for x in sizes):
                sizes.append(s)
        for pid, shop, s in items:
            if s:
                target = next(x for x in sizes if same_size(s, x))
            elif len(sizes) == 1:
                target = sizes[0]
            elif not sizes:
                target = None
            else:
                continue  # unknown size while the name exists in several sizes: can't place it
            gid = hashlib.md5(f"{key}|{target}".encode()).hexdigest()[:12]
            rows.append((pid, gid))

    # A shop that sells several *different* products under one name+size (Rogers: many "ATLETE CALVIN KLEIN
    # JEANS - BLACK / 40" at different URLs and prices) can't be matched: we wouldn't know which one is meant.
    # Variants of one product share a page URL (Shopify ?variant=), so they don't count as different products.
    info = {pid: (shop, (url or "").split("?")[0], price)
            for pid, shop, url, price in con.execute("SELECT id, shop, url, price FROM products")}
    pages = collections.defaultdict(set)
    for pid, gid in rows:
        shop, page, price = info[pid]
        pages[(gid, shop)].add((page, price))
    ambiguous = {k for k, v in pages.items() if len({p for p, _ in v}) > 1 and len({pr for _, pr in v}) > 1}
    rows = [(p, g) for p, g in rows if (g, info[p][0]) not in ambiguous]

    # keep only groups that really span 2+ shops after the size split
    shops_per_group = collections.defaultdict(set)
    for pid, gid in rows:
        shops_per_group[gid].add(info[pid][0])
    rows = [(p, g) for p, g in rows if len(shops_per_group[g]) >= 2]

    con.execute("DELETE FROM matches")
    con.executemany("INSERT INTO matches (product_id, group_id) VALUES (?, ?)", rows)
    con.commit()
    groups = len({g for _, g in rows})
    print(f"{groups:,} products matched across 2+ shops ({len(rows):,} shop listings)")


if __name__ == "__main__":
    main()
