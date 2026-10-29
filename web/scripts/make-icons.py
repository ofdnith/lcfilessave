#!/usr/bin/env python3
"""Render the PWA icons in public/icons from the same shapes as icon.svg, using Pillow only.

Run from web/:  python3 scripts/make-icons.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
SS = 4  # supersampling factor for smooth edges


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def fill(img, mask, color):
    img.paste(Image.new("RGB", img.size, rgb(color)), (0, 0), mask)


def draw_art(img: Image.Image, s: float, ox: float, oy: float):
    """Draw the motif on a 512-unit grid scaled by s, offset by (ox, oy)."""
    d = ImageDraw.Draw(img)
    P = lambda x, y: (ox + x * s, oy + y * s)  # noqa: E731

    def rr(x, y, w, h, rad, color):
        d.rounded_rectangle([*P(x, y), *P(x + w, y + h)], radius=rad * s, fill=rgb(color))

    rr(132, 112, 248, 40, 14, "#3a4757")
    rr(112, 166, 288, 44, 16, "#56677a")
    rr(92, 224, 328, 196, 26, "#e9eef3")

    photo = Image.new("L", img.size, 0)
    ImageDraw.Draw(photo).rounded_rectangle([*P(92, 224), *P(420, 420)], radius=26 * s, fill=255)

    hills = Image.new("L", img.size, 0)
    ImageDraw.Draw(hills).polygon(
        [P(92, 380), P(178, 294), P(242, 358), P(286, 314), P(420, 416), P(420, 420), P(92, 420)], fill=255
    )
    fill(img, ImageChops.multiply(hills, photo), "#9fadbb")

    d = ImageDraw.Draw(img)
    d.ellipse([*P(320, 256), *P(372, 308)], fill=rgb("#f0b44c"))

    edge = Image.new("L", img.size, 0)
    ImageDraw.Draw(edge).rectangle([*P(92, 224), *P(114, 420)], fill=255)
    fill(img, ImageChops.multiply(edge, photo), "#f0b44c")


def background(size):
    top, bottom = rgb("#1e2731"), rgb("#10151c")
    grad = Image.linear_gradient("L").resize((size, size))
    return Image.composite(Image.new("RGB", (size, size), bottom), Image.new("RGB", (size, size), top), grad)


def render(size, maskable=False, rounded=True):
    big = size * SS
    img = background(big)
    if maskable:
        s = big / 512 * 0.78  # keep the motif inside the 80% safe zone
        off = (big - 512 * s) / 2
        draw_art(img, s, off, off)
    else:
        draw_art(img, big / 512, 0, 0)
    if rounded and not maskable:
        m = Image.new("L", (big, big), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, big - 1, big - 1], radius=112 * big / 512, fill=255)
        out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        out.paste(img, (0, 0), m)
        return out.resize((size, size), Image.LANCZOS)
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    render(192).save(OUT / "icon-192.png", optimize=True)
    render(512).save(OUT / "icon-512.png", optimize=True)
    render(192, maskable=True).save(OUT / "maskable-192.png", optimize=True)
    render(512, maskable=True).save(OUT / "maskable-512.png", optimize=True)
    # iOS applies its own corner mask and dislikes transparency: full-bleed square.
    render(180, rounded=False).save(OUT / "apple-touch-icon.png", optimize=True)
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
