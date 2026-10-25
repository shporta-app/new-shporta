"""Zip the browser extension for the stores, from the one `extension/` folder:

    dist/shporta-extension-<version>.zip   Chrome Web Store and Microsoft Edge Add-ons (same package)
    dist/shporta-firefox-<version>.zip     Firefox Add-ons (addons.mozilla.org)

Firefox runs the same code; only the manifest differs: a background script instead of a service worker,
a fixed add-on id, and the data-collection declaration Mozilla requires (we read the product's name, price
and address on the page: "website content").
"""
import copy
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "extension"
SHIP = ["background.js", "content.js", "popup.html", "popup.js", "icons"]


def firefox_manifest(m):
    m = copy.deepcopy(m)
    m["background"] = {"scripts": ["background.js"]}
    m["browser_specific_settings"] = {"gecko": {
        "id": "extension@shporta.app",
        "strict_min_version": "128.0",
        "data_collection_permissions": {"required": ["websiteContent"]},
    }}
    return m


def build(name, manifest):
    out = HERE / "dist" / name
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for item in SHIP:
            path = SRC / item
            for f in ([path] if path.is_file() else sorted(path.rglob("*"))):
                if f.is_file():
                    z.write(f, f.relative_to(SRC).as_posix())
    print(f"{out} ({out.stat().st_size // 1024} KB)")


manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
v = manifest["version"]
build(f"shporta-extension-{v}.zip", manifest)
build(f"shporta-firefox-{v}.zip", firefox_manifest(manifest))
