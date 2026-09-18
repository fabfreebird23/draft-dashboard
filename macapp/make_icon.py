#!/usr/bin/env python3
"""Draw the Bloody Sunday mark — BloodySunday.icns and the app's favicon.

    ./.venv/bin/python make_icon.py

The mark is `theme.cherry_svg` in CoreGraphics: a crimson rounded square, a
white cherry, a white stem. It used to be the cherry emoji, which meant the icon
was Apple's artwork and the browser tab was a different cherry again — and
emoji have no place in this app's chrome anyway. Drawn here, the Dock icon and
the tab are the same mark as the wordmark beside them.

Run once after a design change; both outputs are committed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from AppKit import (NSBezierPath, NSBitmapImageRep, NSColor, NSImage,
                    NSMakeRect, NSMakeSize, NSPNGFileType)

HERE = Path(__file__).resolve().parent
SIZES = [16, 32, 64, 128, 256, 512, 1024]
CRIMSON = (224 / 255, 4 / 255, 63 / 255)      # --crimson, theme.py
BACK = (14 / 255, 13 / 255, 14 / 255)         # the war room's near-black


def _rgb(c, a=1.0):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(c[0], c[1], c[2], a)


def draw(px: int, margin: float = 0.06) -> bytes:
    """The mark at `px`: the crimson tile, the white cherry, the white stem.

    Full bleed rather than sitting on a plate — at 32px in the Dock a mark
    inside a second square reads as a smudge, and this is the same tile the
    wordmark carries in the header.
    """
    img = NSImage.alloc().initWithSize_(NSMakeSize(px, px))
    img.lockFocus()
    m = px * margin
    w = px - 2 * m
    h = w                      # the icon is square; the 34x38 tile is squared up
    x, y = m, m
    _rgb(CRIMSON).set()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, y, w, h), w * 0.2, w * 0.2).fill()
    s = w / 34.0               # the SVG's own 34-wide coordinate space
    NSColor.whiteColor().set()
    cr = 7 * s                 # cherry: r=7 at (15,26), y flipped for Cocoa
    cx, cy = x + 17 * s, y + h - 25 * s
    NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(cx - cr, cy - cr, cr * 2, cr * 2)).fill()
    stem = NSBezierPath.bezierPath()   # the SVG's curve, (16,19) -> (21,10)
    stem.moveToPoint_((x + 18 * s, y + h - 18 * s))
    stem.curveToPoint_controlPoint1_controlPoint2_(
        (x + 23 * s, y + h - 9 * s), (x + 19 * s, y + h - 12 * s), (x + 22 * s, y + h - 10 * s))
    stem.setLineWidth_(2.4 * s)
    stem.setLineCapStyle_(1)   # round
    stem.stroke()
    img.unlockFocus()
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, None))


def main() -> int:
    ic = HERE / "BloodySunday.iconset"
    ic.mkdir(exist_ok=True)
    for px in SIZES:
        (ic / f"icon_{px}x{px}.png").write_bytes(draw(px))
        if px * 2 in (32, 64, 256, 512, 1024):
            (ic / f"icon_{px}x{px}@2x.png").write_bytes(draw(px * 2))
    subprocess.run(["iconutil", "-c", "icns", str(ic), "-o",
                    str(HERE / "BloodySunday.icns")], check=True)
    subprocess.run(["rm", "-rf", str(ic)], check=True)
    fav = HERE.parent / "assets" / "favicon.png"
    fav.write_bytes(draw(256, margin=0.0))
    print("wrote", HERE / "BloodySunday.icns", "and", fav)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
