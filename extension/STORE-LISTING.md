# Chrome Web Store listing: shporta

Upload `dist/shporta-extension-1.0.0.zip` at https://chrome.google.com/webstore/devconsole after creating the
developer account (one-time 5 USD fee, paid by the owner). Copy the fields below.

## Store listing

**Name:** shporta: krahaso çmimet

**Summary (132 characters max):**
A është ky çmim i mirë? shporta të tregon ku e gjen më lirë në Shqipëri, dhe dupe më të lira, ndërsa blen online.

**Description (Albanian first, English below):**

Kur shikon një produkt në një dyqan online, shporta të tregon menjëherë:
- nëse çmimi është i mirë, normal apo i lartë, krahasuar me dyqanet online në Shqipëri
- ku e gjen të njëjtin produkt më lirë, me lidhje direkte te dyqani
- dupe: produkte të tjera që bëjnë të njëjtën punë për shumë më pak (p.sh. i njëjti përbërës aktiv, ose parfum i frymëzuar nga origjinali)

Krahasojmë vetëm të njëjtin produkt: i njëjti emër, e njëjta markë, e njëjta madhësi. Çmimet përditësohen çdo natë nga mbi 100 dyqane
online shqiptare: kozmetikë, farmaci, parfume, veshje, këpucë, ora, syze, bizhuteri.

Privatësia: shtesa lexon vetëm emrin, çmimin dhe adresën e produktit që ke hapur. Nuk lexon fjalëkalime apo pagesa, nuk ruan historinë
dhe nuk shet të dhëna. Më shumë: https://shporta.app/privatesia

---

While you shop online, shporta shows whether the price is good, normal or high compared with Albanian online shops, where the same
product is cheaper, and cheaper dupes that do the same job. It compares only the exact same product (same name, brand and size).
Prices from 100+ Albanian online shops, updated nightly. It reads only the product name, price and address of the page you open.

**Category:** Shopping
**Language:** Albanian (add English as a second language)
**Homepage:** https://shporta.app
**Support / contact:** the professional email you use for shporta
**Privacy policy URL:** https://shporta.app/privatesia

**Graphics** (the owner takes these after loading the extension, see below):
- Icon 128×128: `extension/icons/icon-128.png`
- Screenshots 1280×800: the shporta panel on 2–3 real shop product pages (e.g. a skincare product on a pharmacy site,
  a perfume with a dupe). Use real pages as they appear; don't edit prices.

## Privacy practices tab

**Single purpose:** Show price comparisons and cheaper alternatives for the product the user is viewing on a shopping site.

**Permission justifications:**
- *Host access to all https sites (content script):* the extension must recognise a product page on any online shop the user visits,
  so it reads that page's product name and price (schema.org Product data or page meta tags). It does nothing on pages without a product.
- *Host access to https://shporta.app:* to look up prices and dupes in shporta's database.

**Remote code:** No. All code is in the package.

**Data usage (tick):** "Website content" (product name, price, currency and page address of product pages only).
Not collected: personally identifiable information, health, financial/payment, authentication, personal communications,
location, web history, user activity.
Certify: not sold to third parties; not used for purposes unrelated to the single purpose; not used for creditworthiness or lending.

## Before submitting

1. Load the unpacked `extension` folder in Chrome (chrome://extensions → Developer mode → Load unpacked) and test on 3–4 shops.
2. Take the screenshots from those tests.
3. Zip again if anything changed: `python package_extension.py`.
