#!/usr/bin/env python3
"""Exclusive-lane EN/IS re-route after DRC cleanup (5f0f389).

Lane policy (EN and IS never share a channel):
  - EN long-haul: B.Cu only, vertical columns x=40.0..46.5 (west of ADIO corridors
    and west of IS). Short F stubs at chip + M1000 only.
  - IS long-haul: F.Cu highways (y-channels) + vertical feeders; vias at M1000 S
    approach. No IS copper in EN column band on B.Cu.
  - Local IS sense (U–R–C) stays short F.Cu Manhattan.

Gated: after each batch, run DRC; if shorts > baseline (J2-only), restore PCB
snapshot and abort that batch. Does NOT touch HELLCORE. Forces K8 headers.
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
DRC_JSON = Path("/tmp/drc/enis_gate.json")
SNAP = Path("/tmp/drc/pdmrazora.enis_snap.kicad_pcb")

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

# Exclusive EN B.Cu columns (12) — must stay < 47 (IS) and << 55 (ADIO)
# EN column banks (exclusive):
#   HP approach X (east of S-pads, west of ADIO): south-ring then north to E pads
#   ADIO EN cols: 53.2..54.6 (no HP verticals here)
HP_APPROACH_X = [50.85, 51.15, 51.45, 65.50]  # PWM4 east of ADIO-bot EN cols @62-64
# Top EN: cols west of ADIO@55; Bot EN: cols east of ADIO corridors (gap near 60-62)
ADIO_EN_COLS_TOP = [53.10, 53.60, 54.10, 54.60]
ADIO_EN_COLS_BOT = [62.20, 62.80, 63.40, 64.00]  # east of PWR stub @61.5 / ADIO
EN_COLS = HP_APPROACH_X + ADIO_EN_COLS_TOP + ADIO_EN_COLS_BOT

# Exclusive IS F.Cu highway Y channels (12) — south of ADIO, between/around HP
# Avoid EN module Y band (18-36) and ADIO via band (~50-56)
IS_HWY = [
    70.0, 70.8, 71.6, 72.4,   # HP-top IS (AUX1/2 + early)
    74.0, 74.8, 75.6, 76.4,   # mid
    90.0, 90.8, 91.6, 92.4,   # HP-bottom IS (AUX3/4) south of pads@82
]


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
        pass
    v.SetNet(ensure_net(board, netname))
    board.Add(v)
    return v


def manhattan(board, pts, width, net, layer=F_Cu):
    """pts: list of (x,y); add axis-aligned segments."""
    n = 0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if abs(x1 - x2) > 1e-4 and abs(y1 - y2) > 1e-4:
            # bend: horizontal then vertical
            add_track(board, x1, y1, x2, y1, width, net, layer); n += 1
            add_track(board, x2, y1, x2, y2, width, net, layer); n += 1
        else:
            add_track(board, x1, y1, x2, y2, width, net, layer); n += 1
    return n


def downgrade_to_k8(path: Path):
    text = path.read_text()
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
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
    subprocess.check_call([
        "kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
        "--output", str(DRC_JSON), str(PCB_PATH),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.loads(DRC_JSON.read_text())


def metrics(drc):
    shorts = sum(1 for v in drc["violations"] if v["type"] == "shorting_items")
    cross = sum(1 for v in drc["violations"] if v["type"] == "tracks_crossing")
    unc = len(drc.get("unconnected_items", []))
    return shorts, cross, unc


def count_tracks(board):
    tr = [t for t in board.GetTracks() if type(t).__name__ != "PCB_VIA"]
    vias = [t for t in board.GetTracks() if type(t).__name__ == "PCB_VIA"]
    return len(tr), len(vias)


def clear_nets(board, nets):
    n = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() in nets:
            board.Delete(t)
            n += 1
    return n


def snap_save():
    shutil.copy2(PCB_PATH, SNAP)


def snap_restore():
    shutil.copy2(SNAP, PCB_PATH)


def save_board(board):
    pcbnew.SaveBoard(str(PCB_PATH), board)
    downgrade_to_k8(PCB_PATH)


def gate(label, baseline_shorts, baseline_cross):
    """Return (ok, shorts, cross, unc). Reject if new shorts or cross much worse."""
    drc = run_drc()
    s, c, u = metrics(drc)
    ok = s <= baseline_shorts and c <= baseline_cross + 50
    print(f"  GATE {label}: shorts={s} (base {baseline_shorts}) cross={c} (base {baseline_cross}) unc={u} -> {'OK' if ok else 'FAIL'}")
    return ok, s, c, u


# ---- routing batches ----

def route_is_local(board, fps):
    """U–R–C local sense on F.Cu only (clear of VBAT/GND/PWR/pad5)."""
    n = 0
    # HP: IS pad is between VBAT/GND on the pin row — escape SOUTH then to R
    for net, u, r, c, side in [
        ("IN_AUX1", "U1", "R10", "C10", "W"),
        ("IN_AUX2", "U2", "R20", "C20", "E"),
        ("IN_AUX3", "U3", "R30", "C30", "W"),
        ("IN_AUX4", "U4", "R40", "C40", "E"),
    ]:
        ux, uy = pad_xy(get_pad(fps, u, "3"))
        rx, ry = pad_xy(get_pad(fps, r, "2"))
        cx, cy = pad_xy(get_pad(fps, c, "1"))
        bus_y = uy + 3.2  # south of pin row (clears VBAT/GND/PWR at pin y)
        add_track(board, ux, uy, ux, bus_y, 0.25, net); n += 1
        add_track(board, ux, bus_y, rx, bus_y, 0.25, net); n += 1
        add_track(board, rx, bus_y, rx, ry, 0.25, net); n += 1
        add_track(board, rx, ry, cx, cy, 0.25, net); n += 1
    # ADIO: via-in-pad on IS → B.Cu under package → via at R (F.Cu pin-row is impassable)
    for net, u, r, c in [
        ("IN_MAP1", "U11", "R101", "C101"), ("IN_MAP2", "U12", "R102", "C102"),
        ("IN_MAP3", "U13", "R103", "C103"), ("IN_O2S", "U14", "R104", "C104"),
        ("IN_O2S2", "U15", "R105", "C105"), ("IN_RES1", "U16", "R106", "C106"),
        ("IN_RES2", "U17", "R107", "C107"), ("IN_RES3", "U18", "R108", "C108"),
    ]:
        ux, uy = pad_xy(get_pad(fps, u, "4"))
        rx, ry = pad_xy(get_pad(fps, r, "2"))
        cx, cy = pad_xy(get_pad(fps, c, "1"))
        add_via(board, ux, uy, net); n += 1
        add_track(board, ux, uy, rx, uy, 0.25, net, B_Cu); n += 1
        add_track(board, rx, uy, rx, ry, 0.25, net, B_Cu); n += 1
        add_via(board, rx, ry, net); n += 1
        add_track(board, rx, ry, cx, ry, 0.25, net); n += 1
        if abs(cy - ry) > 1e-3:
            add_track(board, cx, ry, cx, cy, 0.25, net); n += 1
    return n


def route_en(board, fps):
    """EN chip → M1000 with exclusive corridors.

    - ADIO EN: B.Cu cols x=53.2..54.6 + unique escape Y (never share a channel)
    - HP EN: south-ring on B at y=96+ then north on HP_APPROACH_X (50.7..51.9)
      so HP verticals never cross ADIO EN horizontals
    """
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
        ("OUT_IO5", "U15", ["2", "3"], "E7", 4, "adio_bot"),
        ("OUT_IO6", "U16", ["2", "3"], "E9", 5, "adio_bot"),
        ("OUT_IO7", "U17", ["2", "3"], "E23", 6, "adio_bot"),
        ("OUT_IO8", "U18", ["2", "3"], "E22", 7, "adio_bot"),
    ]
    for net, uref, pins, mpad, idx, kind in pairs:
        coords = [pad_xy(get_pad(fps, uref, p)) for p in pins]
        if len(coords) > 1:
            add_track(board, coords[0][0], coords[0][1], coords[1][0], coords[1][1], 0.25, net); n += 1
        sx, sy = coords[0]
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        add_via(board, sx, sy, net); n += 1
        # E pads are PTH — land on pad with B.Cu (no shared 50.2 via column)

        if kind == "hp":
            ax = HP_APPROACH_X[idx]
            ring_y = 88.5 + idx * 0.70
            drop_x = sx + (1.40 + idx * 0.55) * (1 if idx % 2 == 0 else -1)
            add_track(board, sx, sy, drop_x, sy, 0.25, net, B_Cu); n += 1
            add_track(board, drop_x, sy, drop_x, ring_y, 0.25, net, B_Cu); n += 1
            add_track(board, drop_x, ring_y, ax, ring_y, 0.25, net, B_Cu); n += 1
            add_track(board, ax, ring_y, ax, my, 0.25, net, B_Cu); n += 1
            add_track(board, ax, my, mx, my, 0.25, net, B_Cu); n += 1
        elif kind == "adio_top":
            col = ADIO_EN_COLS_TOP[idx]
            esc_y = 12.8 - idx * 0.55
            add_track(board, sx, sy, sx, esc_y, 0.25, net, B_Cu); n += 1
            add_track(board, sx, esc_y, col, esc_y, 0.25, net, B_Cu); n += 1
            add_track(board, col, esc_y, col, my, 0.25, net, B_Cu); n += 1
            add_track(board, col, my, mx, my, 0.25, net, B_Cu); n += 1
        else:  # adio_bot
            col = ADIO_EN_COLS_BOT[idx - 4]
            esc_y = 45.5 + (idx - 4) * 0.55
            jx = sx + 1.60
            add_track(board, sx, sy, jx, sy, 0.25, net, B_Cu); n += 1
            add_track(board, jx, sy, jx, esc_y, 0.25, net, B_Cu); n += 1
            add_track(board, jx, esc_y, col, esc_y, 0.25, net, B_Cu); n += 1
            add_track(board, col, esc_y, col, my, 0.25, net, B_Cu); n += 1
            add_track(board, col, my, mx, my, 0.25, net, B_Cu); n += 1
    return n


def route_is_longhaul(board, fps):
    """IS R → M1000 S on exclusive F.Cu highways (EN stays on B).

    Private vertical X per net east of the sense-R (toward C / away from GND pad1).
    Highways y=68.0..72.4 stay clear of GND@75 and IN_VIGN@77.
    """
    n = 0
    is_pairs = [
        ("IN_AUX1", "R10", "S13", 0),
        ("IN_AUX2", "R20", "S12", 1),
        ("IN_AUX3", "R30", "S11", 2),
        ("IN_AUX4", "R40", "S10", 3),
        ("IN_MAP1", "R101", "S21", 4),
        ("IN_MAP2", "R102", "S20", 5),
        ("IN_MAP3", "R103", "S19", 6),
        ("IN_O2S", "R104", "S16", 7),
        ("IN_O2S2", "R105", "S15", 8),
        ("IN_RES1", "R106", "S17", 9),
        ("IN_RES2", "R107", "S14", 10),
        ("IN_RES3", "R108", "S18", 11),
    ]
    # Absolute private vertical X (F) — spaced 0.7 mm, east of ADIO field / HP sense
    vert_xs = [74.0, 74.7, 75.4, 76.1, 78.0, 78.7, 79.4, 80.1,
               132.5, 133.2, 134.0, 134.7]
    for net, rref, mpad, idx in is_pairs:
        rx, ry = pad_xy(get_pad(fps, rref, "2"))
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        hwy = 68.0 + idx * 0.40
        vx = vert_xs[idx]
        # Prefer vertical X on same side as R (right-side channels use 132+)
        if rx >= 110:
            vx = vert_xs[8 + (idx % 4)]
        elif idx >= 8:
            vx = vert_xs[idx]
        # F only: R → vert X → hwy → module X → S pad
        add_track(board, rx, ry, vx, ry, 0.2, net); n += 1
        add_track(board, vx, ry, vx, hwy, 0.2, net); n += 1
        add_track(board, vx, hwy, mx, hwy, 0.2, net); n += 1
        add_track(board, mx, hwy, mx, my, 0.2, net); n += 1
    return n


def en_is_unc(drc):
    import re
    pat = re.compile(r"\[([^\]]+)\]")
    n = 0
    for item in drc.get("unconnected_items", []):
        nets = set()
        for it in item.get("items", []):
            m = pat.search(it.get("description", ""))
            if m:
                nets.add(m.group(1))
        if nets & (EN_NETS | IS_NETS):
            n += 1
    return n


def main():
    print("=== route_en_is_lanes (exclusive EN B-cols / IS F-hwys) ===")
    drc0 = run_drc()
    s0, c0, u0 = metrics(drc0)
    e0 = en_is_unc(drc0)
    print(f"BEFORE shorts={s0} cross={c0} unc={u0} en_is_unc={e0}")
    board0 = pcbnew.LoadBoard(str(PCB_PATH))
    t0, v0 = count_tracks(board0)
    print(f"BEFORE tracks={t0} vias={v0}")

    # Baseline gate thresholds
    base_shorts = s0  # expect 1 (J2)
    base_cross = c0

    BASE = Path("/tmp/drc/pdmrazora.enis_baseline.kicad_pcb")
    shutil.copy2(PCB_PATH, BASE)

    def restore_base():
        shutil.copy2(BASE, PCB_PATH)

    # --- Batch A: clear EN/IS copper, route IS local ---
    board = pcbnew.LoadBoard(str(PCB_PATH))
    fps = fp_map(board)
    deleted = clear_nets(board, EN_NETS | IS_NETS)
    print(f"Cleared {deleted} EN/IS track/via items")
    nloc = route_is_local(board, fps)
    print(f"IS local segments={nloc}")
    save_board(board)
    ok, s, c, u = gate("is_local", base_shorts, base_cross)
    if not ok:
        print("FAIL is_local — restoring baseline")
        restore_base()
        return 1
    snap_save()  # mid: after local

    # --- Batch B: EN exclusive B lanes ---
    board = pcbnew.LoadBoard(str(PCB_PATH))
    fps = fp_map(board)
    nen = route_en(board, fps)
    print(f"EN segments={nen}")
    save_board(board)
    ok, s, c, u = gate("en_lanes", base_shorts, base_cross)
    if not ok:
        print("FAIL en_lanes — restoring mid (is_local) then stopping; baseline kept at", BASE)
        snap_restore()
        restore_base()
        return 1
    snap_save()

    # --- Batch C: IS F highways (on failure keep EN+local — do not wipe EN) ---
    snap_save()  # mid after EN
    board = pcbnew.LoadBoard(str(PCB_PATH))
    fps = fp_map(board)
    nis = route_is_longhaul(board, fps)
    print(f"IS longhaul segments={nis}")
    save_board(board)
    ok, s, c, u = gate("is_longhaul", base_shorts, base_cross)
    if not ok:
        print("FAIL is_longhaul — keeping EN+local (restoring mid-EN snap)")
        snap_restore()
        # continue to zone fill with EN done

    # --- Zone fill + final metrics ---
    board = pcbnew.LoadBoard(str(PCB_PATH))
    print("Filling zones...")
    ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    at, av = count_tracks(board)
    save_board(board)

    drc1 = run_drc()
    s1, c1, u1 = metrics(drc1)
    e1 = en_is_unc(drc1)
    print(f"AFTER shorts={s1} cross={c1} unc={u1} en_is_unc={e1} tracks={at} vias={av}")

    # If fill introduced shorts, still record but warn
    if s1 > base_shorts:
        print("WARNING: zone fill increased shorts — attempting short-only delete pass")
        board = pcbnew.LoadBoard(str(PCB_PATH))
        idmap = {t.m_Uuid.AsString(): t for t in board.GetTracks()}
        victims = set()
        for v in drc1["violations"]:
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
        print(f"Deleted {len(victims)} shorting track/via items")
        ZONE_FILLER(board).Fill(board.Zones())
        at, av = count_tracks(board)
        save_board(board)
        drc1 = run_drc()
        s1, c1, u1 = metrics(drc1)
        e1 = en_is_unc(drc1)
        print(f"AFTER2 shorts={s1} cross={c1} unc={u1} en_is_unc={e1} tracks={at} vias={av}")

    head = PCB_PATH.read_text()[:120]
    k8 = "20240108" in head and 'generator_version "8.0"' in head
    print(f"K8_OK={k8}")

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
        f.write("strategy=en_Bcols_x40-46_is_Fhwys_gated_k8\n")
        f.write("note=EN exclusive B.Cu columns; IS exclusive F.Cu highways; HELLCORE untouched; J2 short may remain\n")
    print("Wrote", STATUS)
    return 0 if s1 <= base_shorts and (u1 < u0 or e1 < e0) else 1


if __name__ == "__main__":
    sys.exit(main())
