#!/usr/bin/env python3
"""Plot ADIO neck crop and write mm-blocker notes after the ADIO-rest attempt.

No copper is changed. Documents why ADIO1–5/7/8 did not land like ADIO6.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pcbnew
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_109x98 as L


def plot_neck(board, path: Path) -> None:
    # Crop: x=18–109, y=48–86 (south buses + driver row + neck)
    x0, y0, x1, y1 = 18.0, 48.0, 109.0, 86.0
    scale = 12
    w, h = int((x1 - x0) * scale) + 8, int((y1 - y0) * scale) + 8
    img = Image.new("RGB", (w, h), (14, 16, 22))
    dr = ImageDraw.Draw(img, "RGBA")

    def pxy(x, y):
        return int((x - x0) * scale) + 4, int((y - y0) * scale) + 4

    # Keepouts
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if not z.GetIsRuleArea():
            continue
        bbox = z.GetBoundingBox()
        dr.rectangle(
            [
                pxy(L.ToMM(bbox.GetLeft()), L.ToMM(bbox.GetTop())),
                pxy(L.ToMM(bbox.GetRight()), L.ToMM(bbox.GetBottom())),
            ],
            outline=(220, 90, 90),
            width=2,
        )

    # B.Cu tracks
    for t in board.GetTracks():
        if L.is_via(t):
            p = t.GetPosition()
            cx, cy = pxy(L.ToMM(p.x), L.ToMM(p.y))
            if 0 <= cx < w and 0 <= cy < h:
                col = (240, 210, 80) if t.GetNetname().startswith("ADIO") else (200, 200, 210)
                dr.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], outline=col)
            continue
        if t.GetLayer() != pcbnew.B_Cu:
            continue
        a, b = t.GetStart(), t.GetEnd()
        net = t.GetNetname()
        if net.startswith("ADIO"):
            col = (240, 210, 80)
            width = 3 if net == "ADIO6" else 2
        elif net.startswith("OUT_"):
            col = (180, 120, 220)
            width = 1
        elif net.startswith("IN_") or net == "SENSOR_5V":
            col = (120, 200, 160)
            width = 1
        else:
            col = (90, 100, 120)
            width = 1
        dr.line(
            [pxy(L.ToMM(a.x), L.ToMM(a.y)), pxy(L.ToMM(b.x), L.ToMM(b.y))],
            fill=col,
            width=width,
        )

    # Annotate open ADIO ends / targets
    marks = [
        (24.9, 73.0, "ADIO2"),
        (23.7, 73.0, "ADIO4"),
        (72.0, 82.0, "ADIO8"),
        (66.0, 81.4, "ADIO6✓"),
        (72.4, 62.0, "v6"),
        (42.3, 52.5, "A1"),
        (42.3, 49.5, "A3"),
        (42.3, 46.5, "A5"),
        (42.3, 43.5, "A7"),
        (23.2, 76.0, "IR3"),
        (24.4, 76.0, "IR1"),
    ]
    for x, y, lab in marks:
        cx, cy = pxy(x, y)
        dr.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], outline=(255, 120, 80), width=2)
        dr.text((cx + 5, cy - 6), lab, fill=(250, 230, 200))

    dr.text((8, 6), "B.Cu ADIO neck — yellow=ADIO (ADIO6 spine bright), red boxes=pour keepouts", fill=(230, 230, 230))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print("wrote", path)


def main():
    board = pcbnew.LoadBoard(str(L.PCB))
    L.ZONE_FILLER(board).Fill(board.Zones())
    plot_neck(board, Path("scripts/adio_rest_blockers.png"))
    art = Path("/opt/cursor/artifacts")
    art.mkdir(parents=True, exist_ok=True)
    plot_neck(board, art / "adio_rest_blockers.png")
    L.plot_png(board, Path("scripts/copper_fill_overview.png"))
    L.plot_png(board, art / "copper_fill_fb_overview.png")


if __name__ == "__main__":
    main()
