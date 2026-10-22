"""arditfarma.al (WooCommerce whose public Store API returns 0 products). Uses the generic sitemap + JSON-LD
adapter, and strips the " - Farmaci Online ArditFarma" suffix the shop puts in every JSON-LD product name."""
import re

from scrape import scrape_jsonld


def scrape(client, max_pages):
    for row in scrape_jsonld(client, max_pages):
        row["title"] = re.sub(r"\s*-\s*Farmaci Online ArditFarma?\s*$", "", row["title"] or "").strip()
        yield row
