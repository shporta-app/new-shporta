"""Build report.html from data/phia.db: every shop with its status, plus products found in 2+ shops.

    python make_report.py      -> writes report.html (open it in a browser)
"""
import collections
import html
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
STOP = {"the", "and", "me", "per", "for", "with", "de", "la", "dhe", "e", "i", "te", "të"}


def match_key(title):
    """Name + size key; rough first pass until real matching exists."""
    t = unicodedata.normalize("NFKD", title.lower()).encode("ascii", "ignore").decode()
    size = re.findall(r"(\d+(?:[.,]\d+)?)\s*(ml|g|gr|oz)\b", t)
    if not size:
        return None
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*(ml|g|gr|oz)\b", " ", t)
    words = sorted({w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 1 and w not in STOP})
    if len(words) < 3:
        return None
    return " ".join(words) + "|" + size[0][0].replace(",", ".") + size[0][1].replace("gr", "g")


def main():
    con = sqlite3.connect(HERE / "data" / "phia.db", timeout=60)
    shops = con.execute(
        """SELECT s.domain, s.category, s.platform, s.status, COALESCE(s.note,''), s.last_scraped,
                  (SELECT COUNT(*) FROM products p WHERE p.shop = s.domain),
                  (SELECT currency FROM products p WHERE p.shop = s.domain GROUP BY currency ORDER BY COUNT(*) DESC LIMIT 1)
           FROM shops s ORDER BY 7 DESC"""
    ).fetchall()
    total = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    # groups come from match.py; one offer per shop (its cheapest listing, in-stock preferred)
    groups = collections.defaultdict(dict)
    for gid, shop, title, price, cur, stock, url in con.execute(
        """SELECT m.group_id, p.shop, p.title, p.price, p.currency, p.in_stock, p.url
           FROM matches m JOIN products p ON p.id = m.product_id"""
    ):
        o = {"shop": shop, "price": price, "cur": cur, "stock": stock, "title": title, "url": url}
        cur_best = groups[gid].get(shop)
        if cur_best is None or (stock, -price) > (cur_best["stock"], -cur_best["price"]):
            groups[gid][shop] = o
    matches = []
    for v in groups.values():
        offers = sorted(v.values(), key=lambda o: (o["cur"] != "ALL", not o["stock"], o["price"]))
        lek = [o["price"] for o in offers if o["cur"] == "ALL" and o["stock"]]
        gap = round((max(lek) - min(lek)) / max(lek) * 100) if len(lek) >= 2 else 0
        name = max((o["title"] for o in offers), key=len)
        matches.append({"name": name, "offers": offers, "gap": gap, "n": len(offers)})
    matches.sort(key=lambda m: (-m["n"], -m["gap"]))

    by_status = collections.Counter(s[3] for s in shops)
    data = json.dumps({"shops": shops, "matches": matches}, ensure_ascii=False)
    page = TEMPLATE.replace("__DATA__", data.replace("</", "<\\/")).replace(
        "__SUMMARY__",
        f"{total:,} products · {by_status.get('ok', 0)} shops collected · "
        f"{sum(v for k, v in by_status.items() if k != 'ok')} blocked/down/other · "
        f"{len(matches):,} products found in 2+ shops · built {datetime.now():%Y-%m-%d %H:%M}",
    )
    (HERE / "report.html").write_text(page, encoding="utf-8")
    print(f"report.html written: {total:,} products, {len(shops)} shops, {len(matches):,} matches")


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Phia AL report</title>
<style>
:root{--bg:#fafaf7;--fg:#1b1b1f;--mut:#6b6b73;--line:#e4e4de;--ok:#1f7a4d;--bad:#b3261e;--warn:#9a6700;--acc:#3b5bdb}
@media (prefers-color-scheme:dark){:root{--bg:#141417;--fg:#ececef;--mut:#9a9aa3;--line:#2b2b31;--ok:#5cc28f;--bad:#f28b82;--warn:#e3b341;--acc:#91a7ff}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 "Segoe UI",system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:20px 16px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.sum{color:var(--mut)}nav button{font:inherit;padding:6px 12px;border:1px solid var(--line);background:none;color:var(--fg);border-radius:6px;cursor:pointer}
nav button.on{border-color:var(--acc);color:var(--acc)}input{font:inherit;padding:7px 10px;width:100%;max-width:420px;border:1px solid var(--line);border-radius:6px;background:none;color:var(--fg);margin:8px 0}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;cursor:pointer;white-space:nowrap}td.n{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:var(--ok)}.blocked,.error{color:var(--bad)}.down,.no-products,.pending,.skipped{color:var(--warn)}
.card{border-bottom:1px solid var(--line);padding:10px 0}.card b{display:block}.offer{display:flex;gap:10px;font-variant-numeric:tabular-nums}
.offer span:first-child{min-width:80px;text-align:right}.best{color:var(--ok);font-weight:600}a{color:var(--acc)}.wrap{overflow-x:auto}
.note{color:var(--mut);font-size:12px;max-width:340px}
</style></head><body><main>
<h1>Phia AL: data collected so far</h1><div class="sum">__SUMMARY__</div>
<nav style="margin-top:14px"><button class="on" data-t="shops">Shops</button> <button data-t="matches">Same product, different shops</button></nav>
<section id="shops"><input id="qs" placeholder="Filter shops (name, category, status)"><div class="wrap"><table id="st"><thead><tr>
<th data-k="0">Shop</th><th data-k="1">Category</th><th data-k="3">Status</th><th data-k="6">Products</th><th data-k="7">Currency</th><th data-k="2">Platform</th><th data-k="5">Last scraped</th><th>Note</th></tr></thead><tbody></tbody></table></div></section>
<section id="matches" hidden><p class="sum">Matched by product name and size (match.py). Cheapest in-stock lek price first; out-of-stock and EUR offers are listed below it.</p>
<input id="qm" placeholder="Search a product, e.g. cerave, cosrx, niacinamide"><div id="ml"></div></section>
</main><script>
const D=__DATA__;const fmt=(n,c)=>c==='EUR'?'€'+n.toFixed(2):Math.round(n).toLocaleString('en').replace(/,/g,' ')+' L';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let sk=6,sd=-1;
function drawShops(){const q=document.getElementById('qs').value.toLowerCase();
const rows=D.shops.filter(r=>r.join(' ').toLowerCase().includes(q)).sort((a,b)=>{const x=a[sk],y=b[sk];return (x>y?1:x<y?-1:0)*sd});
document.querySelector('#st tbody').innerHTML=rows.map(r=>`<tr><td><a href="https://${esc(r[0])}" target="_blank" rel="noopener">${esc(r[0])}</a></td><td>${esc(r[1])}</td><td class="${esc(r[3])}">${esc(r[3])}</td><td class="n">${r[6].toLocaleString('en')}</td><td>${esc(r[7])}</td><td>${esc(r[2])}</td><td>${esc((r[5]||'').slice(0,16).replace('T',' '))}</td><td class="note">${esc(r[4])}</td></tr>`).join('');}
document.querySelectorAll('#st th[data-k]').forEach(th=>th.onclick=()=>{const k=+th.dataset.k;sd=k===sk?-sd:(k===6?-1:1);sk=k;drawShops()});
function drawMatches(){const q=document.getElementById('qm').value.toLowerCase().split(/\\s+/).filter(Boolean);
const list=D.matches.filter(m=>q.every(w=>m.offers.some(o=>o.title.toLowerCase().includes(w)))).slice(0,200);
document.getElementById('ml').innerHTML=list.map(m=>`<div class="card"><b>${esc(m.name)}</b><span class="sum">${m.n} shops${m.gap?` · up to ${m.gap}% cheaper at the cheapest`:''}</span>${m.offers.map((o,i)=>`<div class="offer ${i===0&&o.stock&&o.cur==='ALL'?'best':''}" style="${o.stock?'':'opacity:.55'}"><span>${fmt(o.price,o.cur)}</span><a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.shop)}</a><span class="sum">${o.stock?'':'out of stock'}</span></div>`).join('')}</div>`).join('')||'<p class="sum">No matches.</p>';}
document.getElementById('qs').oninput=drawShops;document.getElementById('qm').oninput=drawMatches;
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x===b));document.querySelectorAll('section').forEach(s=>s.hidden=s.id!==b.dataset.t)});
drawShops();drawMatches();
</script></body></html>"""

if __name__ == "__main__":
    main()
