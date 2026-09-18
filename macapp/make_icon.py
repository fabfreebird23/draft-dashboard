#!/usr/bin/env python3
"""Draw BloodySunday.icns — the cherry on the near-black the app is themed in.

No designer, no asset: the badge the app's identity came from is a 🍒 on
#0E0D0E, so it is drawn here with CoreGraphics at 1024 and downsampled by
iconutil's own sizes. Run once; the .icns is committed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from AppKit import (NSBezierPath, NSBitmapImageRep, NSColor, NSFont,
                    NSGraphicsContext, NSImage, NSMakeRect, NSMakeSize,
                    NSPNGFileType, NSAttributedString)
from Foundation import NSMutableDictionary

HERE = Path(__file__).resolve().parent
SIZES = [16, 32, 64, 128, 256, 512, 1024]


def draw(px: int) -> bytes:
    img = NSImage.alloc().initWithSize_(NSMakeSize(px, px))
    img.lockFocus()
    inset = px * 0.045
    r = NSMakeRect(inset, inset, px - 2 * inset, px - 2 * inset)
    NSColor.colorWithSRGBRed_green_blue_alpha_(14 / 255, 13 / 255, 14 / 255, 1.0).set()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, px * 0.22, px * 0.22).fill()
    NSColor.colorWithSRGBRed_green_blue_alpha_(0.62, 0.08, 0.14, 1.0).set()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, px * 0.22, px * 0.22).setLineWidth_(px * 0.02)
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, px * 0.22, px * 0.22).stroke()
    attrs = NSMutableDictionary.dictionary()
    attrs["NSFont"] = NSFont.fontWithName_size_("Apple Color Emoji", px * 0.52) or \
        NSFont.systemFontOfSize_(px * 0.52)
    s = NSAttributedString.alloc().initWithString_attributes_("🍒", attrs)
    sz = s.size()
    s.drawAtPoint_(((px - sz.width) / 2, (px - sz.height) / 2))
    img.unlockFocus()
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, None))


def main() -> int:
    ic = HERE / "BloodySunday.iconset"
    ic.mkdir(exist_ok=True)
    for px in SIZES:
        data = draw(px)
        (ic / f"icon_{px}x{px}.png").write_bytes(data)
        if px * 2 in (32, 64, 256, 512, 1024):
            (ic / f"icon_{px}x{px}@2x.png").write_bytes(draw(px * 2))
    subprocess.run(["iconutil", "-c", "icns", str(ic), "-o",
                    str(HERE / "BloodySunday.icns")], check=True)
    subprocess.run(["rm", "-rf", str(ic)], check=True)
    print("wrote", HERE / "BloodySunday.icns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
