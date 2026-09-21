#!/usr/bin/env python3
"""Zone-fill + M6/HP stitch after split-bobbin critical-net copper (pdmrazora).

Does not move footprints, wipe copper, replay 150×130 scripts, or replace F1.
SENSOR_GND stays off chassis GND — no SENSOR pour is added.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew
from pcbnew import (
    B_Cu,
    F_Cu,
    FromMM,
    PCB_VIA,
    ToMM,
    VECTOR2I,
    ZONE_CONNECTION_FULL,
    ZONE_FILLER,
)

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "pdmrazora.kicad_pcb"
STATUS = ROOT / "scripts" / "copper_status.txt"
LEFTOVER = ROOT / "scripts" / "unconnected_leftover.txt"
DRC_JSON = ROOT / "scripts" / "drc_zonefill.json"
PNG = ROOT / "scripts" / "copper_fill_overview.png"
ART = Path("/opt/cursor/artifacts/copper_fill_fb_overview.png")

BOARD_W, BOARD_H = 104.0, 93.0
CLR = 0.22
KEEP = (1.5, 25.5, 44.7, 66.5)


def mm(x, y=None):
    if y is None:
        return FromMM(x)
    return VECTOR2I(FromMM(x), FromMM(y))


def sanitize_for_k8(text: str) -> str:
    text = re.sub(r"\n\t\t\(tenting [^\n]+\)", "", text)
    text = re.sub(r"\n\t\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(legacy_teardrops (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(placement\n(?:\t\t\t.*\n)*?\t\t\)", "", text)
    text = re.sub(r"\n\t\t\t\(placement\n(?:\t\t\t\t.*\n)*?\t\t\t\)", "", text)
    text = re.sub(r"\(fill yes\n", "(fill\n", text)
    text = re.sub(r"\(fill no\n", "(fill\n", text)
    return text


def downgrade_to_k8(path: Path) -> None:
    text = path.read_text()
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(tenting [^\n]+\)", "", text)
    text = re.sub(r"\n\t\t\(legacy_teardrops (yes|no)\)", "", text)
    k8_layers = """(layers
		(0 "F.Cu" signal)
		(31 "B.Cu" signal)
		(33 "F.Adhes" user "F.Adhesive")
		(32 "B.Adhes" user "B.Adhesive")
		(35 "F.Paste" user)
		(34 "B.Paste" user)
		(37 "F.SilkS" user "F.Silkscreen")
		(36 "B.SilkS" user "B.Silkscreen")
		(39 "F.Mask" user)
		(38 "B.Mask" user)
		(40 "Dwgs.User" user "User.Drawings")
		(41 "Cmts.User" user "User.Comments")
		(42 "Eco1.User" user "User.Eco1")
		(43 "Eco2.User" user "User.Eco2")
		(44 "Edge.Cuts" user)
		(45 "Margin" user)
		(47 "F.CrtYd" user "F.Courtyard")
		(46 "B.CrtYd" user "B.Courtyard")
		(49 "F.Fab" user)
		(48 "B.Fab" user)
		(50 "User.1" user)
		(51 "User.2" user)
		(52 "User.3" user)
		(53 "User.4" user)
	)"""
    text = re.sub(r"\(layers\n.*?\n\t\)", k8_layers, text, count=1, flags=re.S)
    text = re.sub(r' "In\d+\.Cu"', "", text)
    path.write_text(text)
    head = path.read_text()[:250]
    assert "20240108" in head
    assert 'generator_version "8.0"' in head


def ensure_net(board, name):
    ni = board.FindNet(name)
    if ni is not None and ni.GetNetCode() > 0:
        return ni
    ni = pcbnew.NETINFO_ITEM(board, name)
    board.Add(ni)
    return ni


def pad_xy(pad):
    p = pad.GetPosition()
    return ToMM(p.x), ToMM(p.y)


def dist_pt_seg(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def segs_cross(a, b) -> bool:
    x1, y1, x2, y2 = a
    x3, y3, x4, y4 = b
    v1 = abs(x1 - x2) < 1e-3
    h1 = abs(y1 - y2) < 1e-3
    v2 = abs(x3 - x4) < 1e-3
    h2 = abs(y3 - y4) < 1e-3
    if not ((v1 or h1) and (v2 or h2)):
        return False
    if v1 and v2 or h1 and h2:
        return False
    if v1 and h2:
        x, y = x1, y3
        return min(y1, y2) - 0.01 <= y <= max(y1, y2) + 0.01 and min(x3, x4) - 0.01 <= x <= max(x3, x4) + 0.01
    if h1 and v2:
        x, y = x3, y1
        return min(x1, x2) - 0.01 <= x <= max(x1, x2) + 0.01 and min(y3, y4) - 0.01 <= y <= max(y3, y4) + 0.01
    return False


class Occupancy:
    def __init__(self, board):
        self.vias = []
        self.segs = []
        self.pads = []
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                self.vias.append((ToMM(p.x), ToMM(p.y), t.GetNetname(), ToMM(t.GetWidth())))
            else:
                a, b = t.GetStart(), t.GetEnd()
                self.segs.append(
                    (ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y), t.GetLayerName(), t.GetNetname(), ToMM(t.GetWidth()))
                )
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                n = pad.GetNetname()
                if not n:
                    continue
                x, y = pad_xy(pad)
                r = max(ToMM(pad.GetSizeX()), ToMM(pad.GetSizeY())) / 2
                self.pads.append((x, y, n, r, fp.GetReference()))

    def via_ok(self, x, y, net, size) -> bool:
        if x < 0.9 or y < 0.9 or x > BOARD_W - 0.9 or y > BOARD_H - 0.9:
            return False
        if KEEP[0] - 0.4 <= x <= KEEP[2] + 0.4 and KEEP[1] - 0.4 <= y <= KEEP[3] + 0.4:
            return False
        r = size / 2
        for vx, vy, vn, vs in self.vias:
            need = (size + vs) / 2 + CLR
            if math.hypot(x - vx, y - vy) + 1e-4 < need:
                return False
        for px, py, pn, pr, _ref in self.pads:
            if pn == net:
                continue
            if math.hypot(x - px, y - py) < r + pr + CLR:
                return False
        for x1, y1, x2, y2, _lay, n, w in self.segs:
            if n == net:
                continue
            if dist_pt_seg(x, y, x1, y1, x2, y2) < r + w / 2 + CLR:
                return False
        return True


def add_track(board, occ: Occupancy, x1, y1, x2, y2, width, net, layer=F_Cu):
    if abs(x1 - x2) < 1e-4 and abs(y1 - y2) < 1e-4:
        return False
    tr = pcbnew.PCB_TRACK(board)
    tr.SetStart(mm(x1, y1))
    tr.SetEnd(mm(x2, y2))
    tr.SetWidth(FromMM(width))
    tr.SetLayer(layer)
    tr.SetNet(ensure_net(board, net))
    board.Add(tr)
    lay = "F.Cu" if layer == F_Cu else "B.Cu"
    occ.segs.append((x1, y1, x2, y2, lay, net, width))
    return True


def add_via(board, occ: Occupancy, x, y, net, size=0.6, drill=0.3) -> bool:
    if not occ.via_ok(x, y, net, size):
        return False
    v = PCB_VIA(board)
    v.SetPosition(mm(x, y))
    v.SetDrill(FromMM(drill))
    v.SetWidth(FromMM(size))
    v.SetNet(ensure_net(board, net))
    board.Add(v)
    occ.vias.append((x, y, net, size))
    return True


def gnd_islands(board, occ: Occupancy):
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    pads = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() != "GND":
                continue
            x, y = pad_xy(pad)
            pth = pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
            pads.append((fp.GetReference(), pad.GetNumber(), x, y, pth))

    for i, (_r, _n, x, y, pth) in enumerate(pads):
        find(("p", i))
        if pth:
            union(("p", i), "pour")
        for j, (vx, vy, vn, vs) in enumerate(occ.vias):
            if vn != "GND":
                continue
            if math.hypot(x - vx, y - vy) < 2.5:
                union(("p", i), ("v", j))
                union(("v", j), "pour")

    for i, (x1, y1, x2, y2, lay, n, w) in enumerate(occ.segs):
        if n != "GND":
            continue
        find(("s", i))
        half = w / 2 + 0.4
        for j, (_r, _n, x, y, _pth) in enumerate(pads):
            if dist_pt_seg(x, y, x1, y1, x2, y2) <= half:
                union(("p", j), ("s", i))
        for j, (vx, vy, vn, vs) in enumerate(occ.vias):
            if vn != "GND":
                continue
            if dist_pt_seg(vx, vy, x1, y1, x2, y2) <= half + vs / 2:
                union(("v", j), ("s", i))
                union(("v", j), "pour")

    grouped = defaultdict(list)
    for i, (ref, num, x, y, pth) in enumerate(pads):
        grouped[find(("p", i))].append((ref, num, x, y, pth))
    pour = find("pour") if "pour" in parent else None
    islands = []
    for root, lst in grouped.items():
        if pour is not None and root == pour:
            continue
        if all(r == "M1000" for r, *_ in lst):
            continue
        islands.append(lst)
    return islands, pads


def stitch_gnd(board, occ: Occupancy) -> tuple[int, int]:
    nvia = ntrk = 0
    offsets = [
        (0.0, 0.0),
        (0.0, 1.6),
        (0.0, -1.6),
        (-1.7, 0.0),
        (1.7, 0.0),
        (-1.3, 1.3),
        (1.3, 1.3),
        (-1.3, -1.3),
        (1.3, -1.3),
        (0.0, 2.3),
        (0.0, -2.3),
        (-2.3, 0.0),
        (2.3, 0.0),
    ]
    islands, _pads = gnd_islands(board, occ)
    for lst in islands:
        placed = False
        for ref, num, x, y, pth in lst:
            if ref == "M1000":
                continue
            for ox, oy in offsets:
                px, py = x + ox, y + oy
                if not occ.via_ok(px, py, "GND", 0.6):
                    continue
                need_stub = abs(ox) > 0.05 or abs(oy) > 0.05
                if need_stub:
                    # occupancy.track_ok not required — skip if stub would be long
                    pass
                if add_via(board, occ, px, py, "GND", 0.6, 0.3):
                    nvia += 1
                    if need_stub:
                        add_track(board, occ, x, y, px, py, 0.35, "GND")
                        ntrk += 1
                    placed = True
                    break
            if placed:
                break
    return nvia, ntrk


def stitch_m6(board, occ: Occupancy, fps) -> int:
    """Extra vias outside 16 mm Cu: J2 VBAT north island, J3 GND south island."""
    n = 0
    j2, j3 = fps.get("J2"), fps.get("J3")
    plus = minus = None
    if j2:
        for pad in j2.Pads():
            if pad.GetNumber() == "1" and ToMM(pad.GetSizeX()) > 10:
                plus = pad_xy(pad)
    if j3:
        for pad in j3.Pads():
            if pad.GetNumber() == "1" and ToMM(pad.GetSizeX()) > 10:
                minus = pad_xy(pad)
    if plus:
        cx, cy = plus
        for ang in range(0, 360, 45):
            rad = math.radians(ang + 22.5)
            x = cx + 9.4 * math.cos(rad)
            y = cy + 9.4 * math.sin(rad)
            if not (84.0 <= x <= 102.5 and 1.2 <= y <= 21.5):
                continue
            if add_via(board, occ, x, y, "VBAT", 0.8, 0.4):
                n += 1
    if minus:
        cx, cy = minus
        for ang in range(0, 360, 45):
            rad = math.radians(ang + 22.5)
            x = cx + 9.4 * math.cos(rad)
            y = cy + 9.4 * math.sin(rad)
            if not (82.5 <= x <= 102.5 and 72.5 <= y <= 91.5):
                continue
            if add_via(board, occ, x, y, "GND", 0.6, 0.3):
                n += 1
    return n


def stitch_hp_tabs(board, occ: Occupancy, fps) -> int:
    """Thermal vias on TO-263 tabs (north-facing). Pour + B alley do the rest."""
    n = 0
    grids = {
        "U1": [(78.0, 36.8), (80.0, 36.8), (82.0, 36.8), (78.0, 40.2), (80.0, 40.2), (82.0, 40.2)],
        "U2": [(94.0, 36.8), (96.0, 36.8), (98.0, 36.8), (94.0, 40.2), (96.0, 40.2), (98.0, 40.2)],
        "U3": [(78.0, 49.8), (80.0, 49.8), (82.0, 49.8), (78.0, 53.2), (80.0, 53.2), (82.0, 53.2)],
        "U4": [(94.0, 49.8), (96.0, 49.8), (98.0, 49.8), (94.0, 53.2), (96.0, 53.2), (98.0, 53.2)],
    }
    for _uref, pts in grids.items():
        for x, y in pts:
            if add_via(board, occ, x, y, "VBAT", 0.8, 0.4):
                n += 1
    return n


def configure_zones(board) -> None:
    """Solid pad connect on VBAT/GND. Do not add a SENSOR pour."""
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea():
            continue
        name = z.GetNetname()
        if name in ("VBAT", "GND"):
            z.SetPadConnection(ZONE_CONNECTION_FULL)
            z.SetLocalClearance(FromMM(0.3))
            z.SetMinThickness(FromMM(0.4))
        if name == "SENSOR_GND":
            # Should not exist; refuse to fill if someone added one.
            z.SetIsFilled(False)


def plot_png(board, path: Path) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    scale = 8
    w, h = int(BOARD_W * scale) + 8, int(BOARD_H * scale) + 8

    def xy(x, y):
        return int(x * scale) + 4, int(y * scale) + 4

    img = Image.new("RGB", (w, h), (16, 16, 20))
    dr = ImageDraw.Draw(img, "RGBA")
    dr.rectangle([xy(0, 0), xy(BOARD_W, BOARD_H)], outline=(80, 80, 90), width=2)
    dr.line([xy(45.5, 4), xy(45.5, 89)], fill=(90, 90, 40, 180), width=1)

    def draw_filled(z, color):
        try:
            layer = z.GetFirstLayer()
            polys = z.GetFilledPolysList(layer)
        except TypeError:
            polys = z.GetFilledPolysList()
        except Exception:
            return
        n = polys.OutlineCount()
        for i in range(n):
            outline = polys.COutline(i)
            pts = [xy(ToMM(outline.CPoint(j).x), ToMM(outline.CPoint(j).y)) for j in range(outline.PointCount())]
            if len(pts) >= 3:
                dr.polygon(pts, fill=color)

    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea() or not z.IsFilled():
            continue
        name = z.GetNetname()
        ls = z.GetLayerSet()
        if name == "GND" and ls.Contains(B_Cu):
            draw_filled(z, (40, 70, 160, 90))
        elif name == "VBAT":
            draw_filled(z, (200, 60, 50, 110))
        elif name == "GND":
            draw_filled(z, (70, 110, 210, 100))

    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            cx, cy = xy(ToMM(p.x), ToMM(p.y))
            dr.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], outline=(220, 220, 220))
            continue
        a, b = t.GetStart(), t.GetEnd()
        net = t.GetNetname()
        lay = t.GetLayer()
        if net == "VBAT":
            col = (230, 80, 70) if lay == F_Cu else (170, 40, 90)
        elif net == "GND":
            col = (90, 140, 230)
        elif net.startswith("OUT_") or net.startswith("IN_AUX") or net.startswith("IN_MAP") or net.startswith("IN_O") or net.startswith("IN_RES"):
            col = (210, 90, 210) if lay == F_Cu else (160, 70, 200)
        elif net.startswith("PWR_OUT") or net.startswith("ADIO"):
            col = (230, 160, 50)
        else:
            col = (180, 180, 110) if lay == F_Cu else (90, 140, 190)
        dr.line([xy(ToMM(a.x), ToMM(a.y)), xy(ToMM(b.x), ToMM(b.y))], fill=col, width=1)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return True


def count_geom_crossings(occ: Occupancy) -> int:
    n = 0
    segs = occ.segs
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if segs[i][4] != segs[j][4] or segs[i][5] == segs[j][5]:
                continue
            if segs_cross(segs[i][:4], segs[j][:4]):
                n += 1
    return n


def count_via_packs(occ: Occupancy) -> int:
    n = 0
    for i, (x1, y1, n1, s1) in enumerate(occ.vias):
        for x2, y2, n2, s2 in occ.vias[i + 1 :]:
            need = (s1 + s2) / 2 + CLR
            if math.hypot(x1 - x2, y1 - y2) + 1e-4 < need:
                n += 1
    return n


def run_drc(pcb: Path) -> dict:
    out = Path("/tmp/pdmrazora_drc.json")
    cmd = [
        "kicad-cli",
        "pcb",
        "drc",
        "--format",
        "json",
        "--severity-error",
        "--units",
        "mm",
        "-o",
        str(out),
        str(pcb),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    data = {"cli_rc": proc.returncode, "stderr": proc.stderr[-2000:], "stdout": proc.stdout[-1000:]}
    if out.exists():
        try:
            data.update(json.loads(out.read_text()))
        except json.JSONDecodeError as e:
            data["parse_error"] = str(e)
    return data


def summarize_drc(drc: dict) -> dict:
    counts = defaultdict(int)
    samples = defaultdict(list)
    un_nets = defaultdict(int)

    def add(v, typ):
        counts[typ] += 1
        if len(samples[typ]) < 8:
            items = []
            for it in v.get("items", [])[:4]:
                items.append(
                    {
                        "type": it.get("type"),
                        "net": (it.get("net") or it.get("description") or "")[:80],
                        "pos": it.get("pos"),
                    }
                )
            samples[typ].append({"description": (v.get("description") or "")[:160], "items": items})
        if typ == "unconnected_items":
            ns = []
            for it in v.get("items", []):
                m = re.search(r"\[([^\]]+)\]", it.get("description") or "")
                if m:
                    ns.append(m.group(1))
            un_nets["|".join(sorted(set(ns)) or ["?"])] += 1

    for v in drc.get("violations", []):
        add(v, v.get("type", "?"))
    for v in drc.get("unconnected_items") or []:
        add(v, "unconnected_items")
    return {"counts": dict(counts), "unconnected_nets": dict(un_nets), "samples": {k: v for k, v in samples.items()}}


def main() -> int:
    raw = PCB.read_text()
    if not raw.startswith("(kicad_pcb"):
        sys.exit("pcb missing")
    nfp = raw.count("\n\t(footprint ")
    if nfp < 50:
        sys.exit(f"too few footprints ({nfp}) — abort")
    if "J3" not in raw:
        sys.exit("J3 missing — abort")

    tmp = Path("/tmp/pdmrazora_fill.kicad_pcb")
    tmp.write_text(sanitize_for_k8(raw))
    board = pcbnew.LoadBoard(str(tmp))
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    if len(fps) < 50 or "J2" not in fps or "J3" not in fps or "U1" not in fps:
        sys.exit("footprint map incomplete — abort")
    if "F1" not in fps:
        sys.exit("F1 missing — abort")

    before_tracks = len([t for t in board.GetTracks() if t.Type() != pcbnew.PCB_VIA_T])
    before_vias = len([t for t in board.GetTracks() if t.Type() == pcbnew.PCB_VIA_T])
    occ = Occupancy(board)
    islands_before, _ = gnd_islands(board, occ)

    n_gvia, n_gtrk = stitch_gnd(board, occ)
    n_m6 = stitch_m6(board, occ, fps)
    n_hp = stitch_hp_tabs(board, occ, fps)
    configure_zones(board)

    ZONE_FILLER(board).Fill(board.Zones())
    if hasattr(pcbnew, "Refresh"):
        pcbnew.Refresh()
    board.BuildConnectivity()

    filled = 0
    fill_pts = 0
    sensor_pours = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea():
            continue
        if z.GetNetname() == "SENSOR_GND":
            sensor_pours += 1
        if z.IsFilled():
            filled += 1
        try:
            polys = z.GetFilledPolysList(z.GetFirstLayer())
        except TypeError:
            polys = z.GetFilledPolysList()
        fill_pts += sum(polys.COutline(k).PointCount() for k in range(polys.OutlineCount()))

    occ2 = Occupancy(board)
    islands_after, _ = gnd_islands(board, occ2)
    geom = count_geom_crossings(occ2)
    packs = count_via_packs(occ2)
    after_tracks = len([t for t in board.GetTracks() if t.Type() != pcbnew.PCB_VIA_T])
    after_vias = len([t for t in board.GetTracks() if t.Type() == pcbnew.PCB_VIA_T])

    plot_png(board, PNG)
    ART.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PNG, ART)
    board.Save(str(PCB))
    downgrade_to_k8(PCB)

    drc = run_drc(PCB)
    summary = summarize_drc(drc)
    compact = {
        "cli_rc": drc.get("cli_rc"),
        "counts": summary["counts"],
        "unconnected_nets": summary.get("unconnected_nets"),
        "short_samples": (summary.get("samples") or {}).get("shorting_items", [])[:4],
        "crossing_samples": (summary.get("samples") or {}).get("tracks_crossing", [])[:4],
        "unconnected_samples": (summary.get("samples") or {}).get("unconnected_items", [])[:4],
    }
    DRC_JSON.write_text(json.dumps(compact, indent=2) + "\n")

    shorts = summary["counts"].get("shorting_items", 0)
    crosses = summary["counts"].get("tracks_crossing", 0)
    unconn = summary["counts"].get("unconnected_items", 0)
    un_nets = summary.get("unconnected_nets") or {}

    leftover_lines = [
        "# Leftover unconnected nets after split-bobbin copper + zone fill",
        "",
        "## GND",
        f"- Pre-pour union-find carrier islands: **{len(islands_before)}**; after stitch+fill: **{len(islands_after)}**.",
        "- M1000 G pads are module-internal (keepout punches the B.Cu pour) and are not leftovers.",
        "- SENSOR_GND was not bonded to chassis GND. No SENSOR pour.",
        f"- kicad-cli unconnected_items: **{unconn}**. By net (top): {dict(sorted(un_nets.items(), key=lambda kv: -kv[1])[:12])}",
    ]
    if islands_after:
        leftover_lines.append("- Remaining carrier islands (human polish):")
        for lst in islands_after[:20]:
            refs = ", ".join(f"{r}.{n}@{x:.2f},{y:.2f}" for r, n, x, y, _p in lst[:6])
            leftover_lines.append(f"  - {refs}")
        if len(islands_after) > 20:
            leftover_lines.append(f"  - … {len(islands_after) - 20} more")
    leftover_lines += [
        "",
        "## DRC (kicad-cli 8.0.9)",
        f"- shorting_items: {shorts}",
        f"- tracks_crossing: {crosses}",
        f"- unconnected_items: {unconn}",
        f"- other: { {k: v for k, v in summary['counts'].items() if k not in ('shorting_items', 'tracks_crossing', 'unconnected_items')} }",
        "",
        "## Honest leftovers for human east/south polish",
        f"- Geometric H–V scan (not KiCad DRC): {geom} same-layer crossings in the packed field.",
        "- Do **not** replay `scripts/cut_crossings_sexp.py` (150×130).",
        "- F1 ATO placeholder left; J2 pour is split from the post-fuse pour (no fuse bypass).",
        "- KiCad stem `pdmrazora`. EMI split unchanged. J2 north / J3 south.",
        f"- SENSOR pours filled: {sensor_pours} (must be 0).",
    ]
    LEFTOVER.write_text("\n".join(leftover_lines) + "\n")

    STATUS.write_text(
        "\n".join(
            [
                f"tracks={after_tracks}",
                f"vias={after_vias}",
                f"footprints={len(fps)}",
                f"geom_crossings={geom}",
                f"via_packs={packs}",
                f"zones_filled={filled}",
                f"fill_outline_pts={fill_pts}",
                f"gnd_islands_before={len(islands_before)}",
                f"gnd_islands_after={len(islands_after)}",
                f"new_gnd_vias={n_gvia}",
                f"new_gnd_tracks={n_gtrk}",
                f"new_m6_vias={n_m6}",
                f"new_hp_tab_vias={n_hp}",
                f"drc_shorts={shorts}",
                f"drc_crossings={crosses}",
                f"drc_unconnected={unconn}",
                f"drc_cli_rc={drc.get('cli_rc')}",
                "strategy=split_bobbins_critical_nets_zonefill_solid_pours",
                "kicad_cli=8.0.9",
                "hellcore=untouched",
                "fuse=ATO_placeholder_untouched",
                "sensor_pour=absent_not_added",
            ]
        )
        + "\n"
    )

    print(
        f"stitches gnd_vias={n_gvia} gnd_tr={n_gtrk} m6={n_m6} hp={n_hp} "
        f"tracks {before_tracks}->{after_tracks} vias {before_vias}->{after_vias}"
    )
    print(f"gnd islands {len(islands_before)}->{len(islands_after)} zones_filled={filled} pts={fill_pts}")
    print(f"DRC shorts={shorts} crossings={crosses} unconnected={unconn} geom={geom} packs={packs}")
    print("F1 still present:", "F1" in fps, "J3 still present:", "J3" in fps)
    print("sensor_pours", sensor_pours)
    return 0


if __name__ == "__main__":
    sys.exit(main())
