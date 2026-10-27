"""Builds every logo file from one drawing: the basket whose lime bar is the best price.

SVGs are written directly; PNGs are rendered at 1024 px by headless Chrome and scaled down with Pillow.
Small sizes (16-32 px) use a heavier drawing so the lines don't dissolve.
Run: python brand/build_brand.py
"""
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS, EXT, OUT = ROOT / "web" / "assets", ROOT / "extension" / "icons", ROOT / "brand"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

INK, LIME, WHITE = "#14121F", "#C6F432", "#FFFFFF"

# the basket in a 100x100 box: handle, open basket, best-price bar
REGULAR = ('<path d="M30 40 C30 14 70 14 70 40" fill="none" stroke="{fg}" stroke-width="8" stroke-linecap="round"/>'
           '<path d="M12 40 H88 L79 82 a6 6 0 0 1 -6 5 H27 a6 6 0 0 1 -6 -5 Z" fill="none" stroke="{fg}" stroke-width="8" stroke-linejoin="round"/>'
           '<rect x="32" y="56" width="36" height="13" rx="6.5" fill="{ac}"/>')
HEAVY = ('<path d="M32 38 C32 13 68 13 68 38" fill="none" stroke="{fg}" stroke-width="11" stroke-linecap="round"/>'
         '<path d="M9 38 H91 L81 83 a5 5 0 0 1 -5 4 H24 a5 5 0 0 1 -5 -4 Z" fill="none" stroke="{fg}" stroke-width="11" stroke-linejoin="round"/>'
         '<rect x="29" y="53" width="42" height="17" rx="8.5" fill="{ac}"/>')


def tile(draw=REGULAR, scale=0.78, radius=22, bg=INK, fg=WHITE, ac=LIME):
    """The mark on its rounded tile (radius 0 = full bleed, for icons the OS rounds itself)."""
    off = 50 * (1 - scale)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<rect width="100" height="100" rx="{radius}" fill="{bg}"/>'
            f'<g transform="translate({off:.1f} {off + 0.5:.1f}) scale({scale})">{draw.format(fg=fg, ac=ac)}</g></svg>')


def bare(fg=INK, ac="#7FAA00", draw=REGULAR):
    """The mark alone, for print and light backgrounds."""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{draw.format(fg=fg, ac=ac)}</svg>'


def shoot(html, w, h, path):
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "p.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000", f"--window-size={w},{h}",
                        "--virtual-time-budget=3000", f"--screenshot={path}", page.as_uri()],
                       check=True, capture_output=True)


def png(svg, sizes):
    """sizes: {path: px}. One 1024 render, then high-quality downscales."""
    with tempfile.TemporaryDirectory() as tmp:
        big = Path(tmp) / "big.png"
        shoot(f'<html><body style="margin:0;background:transparent">{svg.replace("<svg ", "<svg width=1024 height=1024 ", 1)}</body></html>',
              1024, 1024, big)
        im = Image.open(big).convert("RGBA")
        for path, px in sizes.items():
            im.resize((px, px), Image.LANCZOS).save(path, optimize=True)


def main():
    regular, small = tile(), tile(HEAVY, scale=0.84)
    (ASSETS / "shporta-mark.svg").write_text(regular, encoding="utf-8")
    (ASSETS / "favicon.svg").write_text(small, encoding="utf-8")
    for name, svg in {"mark-tile.svg": regular, "mark-tile-small.svg": small,
                      "mark-ink.svg": bare(), "mark-white.svg": bare(WHITE, LIME)}.items():
        (OUT / name).write_text(svg, encoding="utf-8")

    png(regular, {EXT / "icon-128.png": 128, EXT / "icon-48.png": 48, OUT / "mark-1024.png": 1024})
    png(small, {EXT / "icon-32.png": 32, EXT / "icon-16.png": 16})
    # phones round and mask the icon themselves: full-bleed ink, mark inside the maskable safe zone
    png(tile(scale=0.62, radius=0), {ASSETS / "icon-maskable-512.png": 512, ASSETS / "apple-touch-icon.png": 180,
                                     OUT / "instagram-avatar.png": 1080})
    # installed on a computer the icon is shown as is, so it keeps its own rounded corners
    png(regular, {ASSETS / "icon-512.png": 512, ASSETS / "icon-192.png": 192})
    # /favicon.ico for browsers and apps that never read the <link> tags
    with tempfile.TemporaryDirectory() as tmp:
        sizes = {Path(tmp) / f"{px}.png": px for px in (16, 32, 48)}
        png(small, sizes)
        imgs = [Image.open(f) for f in sizes]
        imgs[-1].save(ROOT / "web" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=imgs[:-1])

    og = (ROOT / "brand" / "og.html").read_text(encoding="utf-8").replace("{MARK}", regular)
    shoot(og, 1200, 630, ASSETS / "og.png")
    print("ok")


if __name__ == "__main__":
    main()
