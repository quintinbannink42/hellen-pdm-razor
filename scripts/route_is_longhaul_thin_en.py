#!/usr/bin/env python3
"""Finish remaining 9 IS long-haul nets, then thin EN B geometry.

Phase 1 — IS long-haul (AUX2/3, MAP2/3, O2S/O2S2, RES1–3):
  Exclusive B.Cu south-ring, unique feeder X + highway Y per net, via at R pad2.
  Escape EAST then SOUTH off R (pad1 is GND). Land on M1000 S (PTH) from the south.
  Per-net DRC gate: reject if shorts > baseline (J2-only).

Phase 2 — EN B re-geometry (no IS copper edits):
  HP westbound highways at y=55.4–56.9 (north of PWR vias @57.55).
  ADIO bot highways at y=53.2–54.7 (south of SENSOR_5V @52.5 and IS local).
  ADIO top escape at y=2.8–4.45 (north of SENSOR_5V bus @y=5).
  HP approach X 50.70–52.20 (west of ADIO corridors / bot EN cols).

Does NOT touch HELLCORE / Micro Core. Forces K8 headers after save.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pcbnew
from pcbnew import (
    VECTOR2I, FromMM, ToMM, PCB_TRACK, PCB_VIA, F_Cu, B_Cu, ZONE_FILLER,
)

ROOT = Path(__file__).resolve().parents[1]
PCB_PATH = ROOT / "pdmrazora.kicad_pcb"
STATUS = ROOT / "scripts" / "copper_status.txt"
DRC_JSON = Path("/tmp/drc/is_en_gate.json")
SNAP = Path("/tmp/drc/pdmrazora.gate_snap.kicad_pcb")
BASE = Path("/tmp/drc/pdmrazora.baseline.kicad_pcb")

EN_NETS = {
    "OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4",
    "OUT_PWM5", "OUT_PWM6", "OUT_PWM7", "OUT_PWM8",
    "OUT_IO5", "OUT_IO6", "OUT_IO7", "OUT_IO8",
}
IS_NETS = {
    "IN_AUX1", "IN_AUX2", "IN_AUX3", "IN_AUX4",
    "IN_MAP1", "IN_MAP2", "IN_MAP3", "IN_O2S",
    "IN_O2S2", "IN_RES1", "IN_RES2", "IN_RES3",
}
# (net, R, M1000-S, unique jog_y south of R — never share a jog Y)
REMAINING_IS = [
    ("IN_AUX2", "R20", "S12", 64.40),
    ("IN_AUX3", "R30", "S11", 86.40),
    ("IN_MAP2", "R102", "S20", 24.70),
    ("IN_MAP3", "R103", "S19", 25.70),
    ("IN_O2S", "R104", "S16", 27.20),
    ("IN_O2S2", "R105", "S15", 50.60),
    ("IN_RES1", "R106", "S17", 51.20),
    ("IN_RES2", "R107", "S14", 51.80),
    ("IN_RES3", "R108", "S18", 52.40),
]

# Unique south-ring Y. Skip J1 pin band (93–105) and mounting band (107.5–111.5).
HWY_POOL = [
    113.20, 118.80, 119.30, 119.80,
    121.50, 123.50, 125.50, 127.50,
    128.20, 112.00, 114.90,
]
# Feeders west of J1 (64.3–64.9) or east of pins/mounting (>=93.6) or 87.4–88.5 gap.
# Avoid EN cols, ADIO/PWR/SENSOR spines, existing IS 70/73/138.25, J1 65–85.
# Avoid bot-EN jx ≈ 70.0 / 88.0 / 106.0 / 124.0 (±0.6) and J1 / mounting.
FEED_POOL = [
    64.30, 64.90, 93.60, 96.00, 99.00, 111.00,
    114.00, 116.50, 125.00, 128.00, 132.20, 133.50,
    135.50, 136.50, 137.50, 139.00, 145.50, 146.20, 148.20,
]

# HP approach: two west of SENSOR@52, two east of bot-EN@64 / west of SENSOR tap@66.58
HP_APPROACH_X = [50.70, 51.25, 60.40, 60.95]  # PWM3/4 west of bot-EN cols
ADIO_EN_COLS_TOP = [53.10, 53.60, 54.10, 54.60]
ADIO_EN_COLS_BOT = [62.20, 62.80, 63.40, 64.00]
HP_HWY = [55.40, 55.90, 56.40, 56.90]
BOT_HWY = [53.20, 53.70, 54.20, 54.70]
TOP_ESC = [4.45, 3.90, 3.35, 2.80]
HP_DROP = [1.50, 1.50, 2.50, 2.50]  # unique X for stacked U1/U3 and U2/U4
BOT_JX = 2.80  # east of IS jog at R+0.90
J1_PAD_BOX = (65.0, 85.0, 93.5, 104.5)  # x0,x1,y0,y1 pin field
J1_MOUNT = [(58.75, 109.50, 1.85), (91.25, 109.50, 1.85)]


def mm(x, y=None):
    if y is None:
        return FromMM(x)
    return VECTOR2I(FromMM(x), FromMM(y))


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


def fp_map(board):
    return {fp.GetReference(): fp for fp in board.GetFootprints()}


def get_pad(fps, ref, num):
    pad = fps[ref].FindPadByNumber(str(num))
    if pad is None:
        raise KeyError(f"{ref}.{num}")
    return pad


def add_track(board, x1, y1, x2, y2, width_mm, netname, layer=F_Cu):
    if abs(x1 - x2) < 1e-4 and abs(y1 - y2) < 1e-4:
        return None
    tr = PCB_TRACK(board)
    tr.SetStart(mm(x1, y1))
    tr.SetEnd(mm(x2, y2))
    tr.SetWidth(FromMM(width_mm))
    tr.SetLayer(layer)
    tr.SetNet(ensure_net(board, netname))
    board.Add(tr)
    return tr


def add_via(board, x, y, netname, drill=0.3, size=0.6):
    v = PCB_VIA(board)
    v.SetPosition(mm(x, y))
    v.SetDrill(FromMM(drill))
    try:
        v.SetWidth(F_Cu, FromMM(size))
        v.SetWidth(B_Cu, FromMM(size))
    except Exception:
        try:
            v.SetFrontWidth(FromMM(size))
        except Exception:
            pass
    v.SetNet(ensure_net(board, netname))
    board.Add(v)
    return v


def has_via_near(board, x, y, netname, tol=0.35):
    for t in board.GetTracks():
        if type(t).__name__ != "PCB_VIA":
            continue
        if t.GetNetname() != netname:
            continue
        p = t.GetPosition()
        if abs(ToMM(p.x) - x) < tol and abs(ToMM(p.y) - y) < tol:
            return True
    return False


def downgrade_to_k8(path: Path):
    text = path.read_text()
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    # Keep existing tenting / embedded_fonts (already on HEAD); strip only new K9 extras
    # if a full K9 rewrite introduced a board-level embedded_fonts we already had that.
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
    path.write_text(text)


def run_drc():
    DRC_JSON.parent.mkdir(parents=True, exist_ok=True)
    if DRC_JSON.exists():
        DRC_JSON.unlink()
    proc = subprocess.run([
        "kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
        "--output", str(DRC_JSON), str(PCB_PATH),
    ], capture_output=True, text=True)
    err = (proc.stderr or "") + (proc.stdout or "")
    if not DRC_JSON.exists() or "Saved DRC Report" not in err:
        raise RuntimeError(f"DRC failed rc={proc.returncode}: {err[-800:]}")
    return json.loads(DRC_JSON.read_text())


def metrics(drc):
    shorts = sum(1 for v in drc["violations"] if v["type"] == "shorting_items")
    cross = sum(1 for v in drc["violations"] if v["type"] == "tracks_crossing")
    unc = len(drc.get("unconnected_items", []))
    return shorts, cross, unc


def en_is_unc(drc):
    pat = re.compile(r"\[([^\]]+)\]")
    n = 0
    open_nets = set()
    for item in drc.get("unconnected_items", []):
        nets = set()
        for it in item.get("items", []):
            m = pat.search(it.get("description", ""))
            if m:
                nets.add(m.group(1))
        hit = nets & (EN_NETS | IS_NETS)
        if hit:
            n += 1
            open_nets |= hit
    return n, sorted(open_nets)


def count_tracks(board):
    tr = [t for t in board.GetTracks() if type(t).__name__ != "PCB_VIA"]
    vias = [t for t in board.GetTracks() if type(t).__name__ == "PCB_VIA"]
    return len(tr), len(vias)


def save_board(board):
    pcbnew.SaveBoard(str(PCB_PATH), board)
    downgrade_to_k8(PCB_PATH)


def snap_save():
    shutil.copy2(PCB_PATH, SNAP)


def snap_restore():
    shutil.copy2(SNAP, PCB_PATH)


def clear_nets(board, nets):
    n = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() in nets:
            board.Delete(t)
            n += 1
    return n


def route_one_is(board, fps, net, rref, mpad, feeder_x, hwy_y, jog_y):
    """B.Cu south-ring from R pad2 to M1000 S pad. Return segment count."""
    rx, ry = pad_xy(get_pad(fps, rref, "2"))
    mx, my = pad_xy(get_pad(fps, "M1000", mpad))
    n = 0
    if not has_via_near(board, rx, ry, net):
        add_via(board, rx, ry, net)
        n += 1
    jog_x = min(rx + 0.90, 148.8)  # east, away from GND pad1
    jog_y = min(max(jog_y, ry + 1.05), 128.8)
    feeder_x = min(max(feeder_x, 1.2), 148.8)
    hwy_y = min(max(hwy_y, 1.2), 128.8)
    add_track(board, rx, ry, jog_x, ry, 0.25, net, B_Cu); n += 1
    add_track(board, jog_x, ry, jog_x, jog_y, 0.25, net, B_Cu); n += 1
    add_track(board, jog_x, jog_y, feeder_x, jog_y, 0.25, net, B_Cu); n += 1
    add_track(board, feeder_x, jog_y, feeder_x, hwy_y, 0.25, net, B_Cu); n += 1
    add_track(board, feeder_x, hwy_y, mx, hwy_y, 0.25, net, B_Cu); n += 1
    add_track(board, mx, hwy_y, mx, my, 0.25, net, B_Cu); n += 1
    return n


def j1_feeder_ok(feeder_x, y_a, y_b):
    """Reject feeders whose vertical runs through SuperSeal pins."""
    y0, y1 = min(y_a, y_b), max(y_a, y_b)
    x0, x1, py0, py1 = J1_PAD_BOX
    if x0 <= feeder_x <= x1 and not (y1 < py0 or y0 > py1):
        return False
    for mx, my, r in J1_MOUNT:
        if abs(feeder_x - mx) < r + 0.25 and not (y1 < my - r or y0 > my + r):
            return False
    return True


def hwy_ok(hwy_y, mx):
    """Reject highways that clip J1 mounting pads."""
    for px, py, r in J1_MOUNT:
        # full-width highways pass through mount X
        if abs(hwy_y - py) < r + 0.25:
            return False
    if 93.5 <= hwy_y <= 104.5:
        return False
    return True


def candidate_pairs(rx, ry, mx, used_feed, used_hwy, jog_y):
    """Prefer feeders east of R, highways south of existing IS ring, J1-clear."""
    feeds = [x for x in FEED_POOL if x not in used_feed]
    hwys = [y for y in HWY_POOL if y not in used_hwy]
    feeds.sort(key=lambda x: (0 if x >= rx + 0.8 else 1, abs(x - (rx + 4.0))))
    hwys.sort(key=lambda y: (0 if y >= 113.0 else 1, abs(y - 119.0)))
    pairs = []
    for y in hwys:
        if not hwy_ok(y, mx):
            continue
        for x in feeds:
            if not j1_feeder_ok(x, jog_y, y):
                continue
            pairs.append((x, y))
    return pairs


def route_en_v2(board, fps, kinds=None):
    """Thinned exclusive B.Cu EN lanes. Returns segment count."""
    n = 0
    pairs = [
        ("OUT_PWM1", "U1", ["2"], "E27", 0, "hp"),
        ("OUT_PWM2", "U2", ["2"], "E17", 1, "hp"),
        ("OUT_PWM3", "U3", ["2"], "E16", 2, "hp"),
        ("OUT_PWM4", "U4", ["2"], "E15", 3, "hp"),
        ("OUT_PWM5", "U11", ["2", "3"], "E14", 0, "adio_top"),
        ("OUT_PWM6", "U12", ["2", "3"], "E26", 1, "adio_top"),
        ("OUT_PWM7", "U13", ["2", "3"], "E25", 2, "adio_top"),
        ("OUT_PWM8", "U14", ["2", "3"], "E28", 3, "adio_top"),
        ("OUT_IO5", "U15", ["2", "3"], "E7", 0, "adio_bot"),
        ("OUT_IO6", "U16", ["2", "3"], "E9", 1, "adio_bot"),
        ("OUT_IO7", "U17", ["2", "3"], "E23", 2, "adio_bot"),
        ("OUT_IO8", "U18", ["2", "3"], "E22", 3, "adio_bot"),
    ]
    for net, uref, pins, mpad, idx, kind in pairs:
        if kinds is not None and kind not in kinds:
            continue
        coords = [pad_xy(get_pad(fps, uref, p)) for p in pins]
        if len(coords) > 1:
            add_track(board, coords[0][0], coords[0][1], coords[1][0], coords[1][1], 0.25, net); n += 1
        sx, sy = coords[0]
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        add_via(board, sx, sy, net); n += 1

        if kind == "hp":
            ax = HP_APPROACH_X[idx]
            hwy = HP_HWY[idx]
            drop_x = sx + HP_DROP[idx]  # unique vs stacked HP pair
            add_track(board, sx, sy, drop_x, sy, 0.25, net, B_Cu); n += 1
            add_track(board, drop_x, sy, drop_x, hwy, 0.25, net, B_Cu); n += 1
            add_track(board, drop_x, hwy, ax, hwy, 0.25, net, B_Cu); n += 1
            add_track(board, ax, hwy, ax, my, 0.25, net, B_Cu); n += 1
            add_track(board, ax, my, mx, my, 0.25, net, B_Cu); n += 1
        elif kind == "adio_top":
            col = ADIO_EN_COLS_TOP[idx]
            esc_y = TOP_ESC[idx]
            add_track(board, sx, sy, sx, esc_y, 0.25, net, B_Cu); n += 1
            add_track(board, sx, esc_y, col, esc_y, 0.25, net, B_Cu); n += 1
            add_track(board, col, esc_y, col, my, 0.25, net, B_Cu); n += 1
            add_track(board, col, my, mx, my, 0.25, net, B_Cu); n += 1
        else:
            col = ADIO_EN_COLS_BOT[idx]
            hwy = BOT_HWY[idx]
            jx = sx + BOT_JX
            add_track(board, sx, sy, jx, sy, 0.25, net, B_Cu); n += 1
            add_track(board, jx, sy, jx, hwy, 0.25, net, B_Cu); n += 1
            add_track(board, jx, hwy, col, hwy, 0.25, net, B_Cu); n += 1
            add_track(board, col, hwy, col, my, 0.25, net, B_Cu); n += 1
            add_track(board, col, my, mx, my, 0.25, net, B_Cu); n += 1
    return n


def kill_new_shorts(board, drc):
    idmap = {t.m_Uuid.AsString(): t for t in board.GetTracks()}
    victims = set()
    for v in drc["violations"]:
        if v["type"] != "shorting_items":
            continue
        blob = json.dumps(v)
        if "J2" in blob and "VBAT" in blob and "GND" in blob:
            continue
        ids = [it["uuid"] for it in v["items"] if it["uuid"] in idmap]
        if not ids:
            continue

        def score(uid):
            obj = idmap[uid]
            try:
                return ToMM(obj.GetLength()) + (30 if type(obj).__name__ == "PCB_VIA" else 0)
            except Exception:
                return 10

        victims.add(max(ids, key=score))
    for uid in victims:
        board.Delete(idmap[uid])
    return len(victims)


def main():
    print("=== route remaining IS long-haul + thin EN B ===")
    DRC_JSON.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PCB_PATH, BASE)

    drc0 = run_drc()
    s0, c0, u0 = metrics(drc0)
    e0, open0 = en_is_unc(drc0)
    board0 = pcbnew.LoadBoard(str(PCB_PATH))
    t0, v0 = count_tracks(board0)
    print(f"BEFORE shorts={s0} cross={c0} unc={u0} en_is_unc={e0} open={open0} tracks={t0} vias={v0}")
    base_shorts = s0

    # ----- Phase 1: remaining IS -----
    used_feed, used_hwy = {70.00, 73.00, 138.25}, {110.50, 112.15, 112.70}
    landed = []
    failed = []
    snap_save()
    for net, rref, mpad, jog_y in REMAINING_IS:
        board = pcbnew.LoadBoard(str(PCB_PATH))
        fps = fp_map(board)
        rx, ry = pad_xy(get_pad(fps, rref, "2"))
        mx, _my = pad_xy(get_pad(fps, "M1000", mpad))
        ok_net = False
        last_scu = None
        cands = candidate_pairs(rx, ry, mx, used_feed, used_hwy, jog_y)[:40]
        if not cands:
            print(f"  NO CANDIDATES {net} R=({rx:.2f},{ry:.2f})")
            failed.append((net, None))
            continue
        for feeder_x, hwy_y in cands:
            snap_save()
            board = pcbnew.LoadBoard(str(PCB_PATH))
            fps = fp_map(board)
            nseg = route_one_is(board, fps, net, rref, mpad, feeder_x, hwy_y, jog_y)
            save_board(board)
            drc = run_drc()
            s, c, u = metrics(drc)
            e, opn = en_is_unc(drc)
            last_scu = (s, c, u, e, feeder_x, hwy_y, nseg)
            if s <= base_shorts and net not in opn:
                used_feed.add(feeder_x)
                used_hwy.add(hwy_y)
                landed.append((net, feeder_x, hwy_y, s, c, u, e))
                print(f"  LAND {net}: feed={feeder_x:.2f} hwy={hwy_y:.2f} segs={nseg} shorts={s} cross={c} unc={u} en_is={e}")
                ok_net = True
                snap_save()
                break
            snap_restore()
        if not ok_net:
            failed.append((net, last_scu))
            print(f"  FAIL {net}: last={last_scu}")
            snap_restore()

    print(f"IS landed {len(landed)}/{len(REMAINING_IS)} failed={ [n for n,_ in failed] }")

    # ----- Phase 2: thin EN in gated families -----
    def try_en(label, kinds):
        snap_save()
        board = pcbnew.LoadBoard(str(PCB_PATH))
        fps = fp_map(board)
        # delete only the nets we are rebuilding
        net_by_kind = {
            "hp": {"OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4"},
            "adio_top": {"OUT_PWM5", "OUT_PWM6", "OUT_PWM7", "OUT_PWM8"},
            "adio_bot": {"OUT_IO5", "OUT_IO6", "OUT_IO7", "OUT_IO8"},
        }
        nets = set()
        for k in kinds:
            nets |= net_by_kind[k]
        deleted = clear_nets(board, nets)
        # route only those kinds
        nseg = route_en_v2(board, fps, kinds)
        save_board(board)
        drc = run_drc()
        s, c, u = metrics(drc)
        e, opn = en_is_unc(drc)
        print(f"  GATE {label}: del={deleted} segs={nseg} shorts={s} cross={c} unc={u} en_is={e} open={opn}")
        if s > base_shorts or (set(opn) & nets):
            print(f"  FAIL {label} — restore")
            snap_restore()
            return False, s, c
        snap_save()
        return True, s, c

    en_ok_hp, _, _ = try_en("en_hp", ["hp"])
    en_ok_bot, _, _ = try_en("en_bot", ["adio_bot"])
    en_ok_top, _, _ = try_en("en_top", ["adio_top"])
    en_ok = en_ok_hp or en_ok_bot or en_ok_top
    print(f"EN families hp={en_ok_hp} bot={en_ok_bot} top={en_ok_top}")

    # ----- Zone fill -----
    board = pcbnew.LoadBoard(str(PCB_PATH))
    print("Filling zones...")
    ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    at, av = count_tracks(board)
    save_board(board)

    drc1 = run_drc()
    s1, c1, u1 = metrics(drc1)
    e1, open1 = en_is_unc(drc1)
    print(f"AFTER fill shorts={s1} cross={c1} unc={u1} en_is={e1} open={open1} tracks={at} vias={av}")

    if s1 > base_shorts:
        print("WARNING: zone fill increased shorts — short-only delete pass")
        board = pcbnew.LoadBoard(str(PCB_PATH))
        ndel = kill_new_shorts(board, drc1)
        print(f"Deleted {ndel} shorting track/via items")
        ZONE_FILLER(board).Fill(board.Zones())
        at, av = count_tracks(board)
        save_board(board)
        drc1 = run_drc()
        s1, c1, u1 = metrics(drc1)
        e1, open1 = en_is_unc(drc1)
        print(f"AFTER2 shorts={s1} cross={c1} unc={u1} en_is={e1} open={open1} tracks={at} vias={av}")

    head = PCB_PATH.read_text()[:120]
    k8 = "20240108" in head and 'generator_version "8.0"' in head
    print(f"K8_OK={k8} en_ok={en_ok}")

    with STATUS.open("w") as f:
        f.write(f"before_shorts={s0}\n")
        f.write(f"before_crossings={c0}\n")
        f.write(f"before_unc={u0}\n")
        f.write(f"before_en_is_unc={e0}\n")
        f.write(f"before_tracks={t0}\n")
        f.write(f"before_vias={v0}\n")
        f.write(f"after_shorts={s1}\n")
        f.write(f"after_crossings={c1}\n")
        f.write(f"after_unc={u1}\n")
        f.write(f"after_en_is_unc={e1}\n")
        f.write(f"after_tracks={at}\n")
        f.write(f"after_vias={av}\n")
        f.write(f"is_landed={','.join(n for n, *_ in landed)}\n")
        f.write(f"is_failed={','.join(n for n, _ in failed)}\n")
        f.write(f"en_regeometry={'ok' if en_ok else 'reverted'}\n")
        f.write("strategy=is_southring_gated_plus_en_B_thin_k8\n")
        f.write("note=9 IS long-haul B.Cu south-ring gated; EN B re-geometry north of PWR / south of SENSOR; HELLCORE untouched; J2 short may remain\n")
    print("Wrote", STATUS)

    ok = s1 <= base_shorts and e1 == 0 and c1 < c0
    if e1 != 0:
        print(f"EN/IS still open: {open1}")
    if c1 >= c0:
        print(f"crossings not reduced: {c0} -> {c1}")
    return 0 if (s1 <= base_shorts and e1 == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
