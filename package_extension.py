"""Zip the browser extension for the Chrome Web Store: dist/shporta-extension-<version>.zip"""
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "extension"
SHIP = ["manifest.json", "background.js", "content.js", "icons"]

version = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))["version"]
out = HERE / "dist" / f"shporta-extension-{version}.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for name in SHIP:
        path = SRC / name
        for f in ([path] if path.is_file() else sorted(path.rglob("*"))):
            if f.is_file():
                z.write(f, f.relative_to(SRC).as_posix())
print(f"{out} ({out.stat().st_size // 1024} KB): {', '.join(z.filename for z in zipfile.ZipFile(out).infolist())}")
