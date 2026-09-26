# Board status — PowerCore (`pdmrazora` rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module. File format stays **20240108 / generator_version 8.0**. Stem is `pdmrazora`.

## This commit — even ADIO NC bridges

ADIO2 now has a poured series neck of **4.53 mm** F+B, above the 1 oz / 20 °C line for 8 A (3.47 mm). SuperSeal pins 2 and 9 join the ADIO2 net on the PCB so the west cage slots merge into that one corridor. The loom table still calls those pins N/C: no harness wire is added, and no signal pin was reassigned. Applicator: `scripts/even_nc_pour.py`. Numbers: [scripts/adio_ampacity.txt](scripts/adio_ampacity.txt).

Pin 25 stays N/C. Joining it to ADIO8 does not produce a continuous path to U18 at 3.47 mm (widest zone-aware path is about 0.80 mm, pinch beside U18). ADIO4 and ADIO6 stay at that same ~0.80 mm path once the odd pours and the PWR_OUT copper are treated as obstacles. The pad-only sum of every 0.52–0.60 mm slot around one pin (~5.66 mm) is not a series neck and was not poured. ADIO7's B.Cu leg was not moved.

Outline stays **(−32, −40)–(142, 162)**. F1 stays open. There is still no SENSOR_GND pour. Copper is still 1 oz. No gerbers.

| Path | Series neck | 20 °C need |
|------|-------------|------------|
| ADIO1 | 1.75 + 1.76 mm = 3.51 mm, no via | 3.47 mm |
| ADIO3 | 3.80 mm B.Cu under PWR_OUT2 east | 3.47 mm |
| ADIO5 | 3.80 mm B.Cu under PWR_OUT2 east | 3.47 mm |
| ADIO7 | 3.80 mm B.Cu (outline not moved) | 3.47 mm |
| ADIO2 | 4.53 mm F+B filled corridor via pins 2 and 9 | 3.47 mm |
| ADIO4 | not poured; widest path ~0.80 mm | 3.47 mm |
| ADIO6 | not poured; widest path ~0.80 mm | 3.47 mm |
| ADIO8 | not poured; widest path ~0.80 mm with pin 25 | 3.47 mm |
| PWR_OUT1–4 | unchanged 16.72 mm class pours | 16.72 mm |

Series neck is the minimum F+B cross-section of one continuous path (filled copper, layers on the same XY add, via drills are holes the path goes around). It is not the sum of parallel slots.

| Issue | Before | After |
|-------|-------:|------:|
| shorting_items / crossings / clearance / courtyard / padstack / mask bridge | 0 | **0** |
| unconnected_items | 184 | **183** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged | no | **no** |
| In1.Cu count | 181 | **181** |

Unconnected is one lower. ADIO2's power path dropped from 7 open items to the one sense pad (R202.2 at y=56.20), same class as the odd channels. GND went 55 → 60 because the B.Cu ribbon pushes priority-1 GND aside. `kicad-cli` 8.0.9, `--severity-error`. `scripts/cut_crossings_sexp.py` was not replayed. Pins were not frozen.

## Previous commit — even ADIO fanout

ADIO2, ADIO4, ADIO6, and ADIO8 still do not have a 3.47 mm neck. A read-only corridor search (`scripts/even_adio_fanout.py`, also `scripts/adio_ampacity.py --even-audit`) may leave each even pin in any direction, on F.Cu and on B.Cu. The widest single neck is **0.60 mm on a layer, F+B 1.20 mm**. The 1 oz ceiling, with copper flush to the 1.3 mm drills and zero clearance (a short to the next plating), is **F+B 3.40 mm**, still under 3.47 mm. Detail: [scripts/adio_ampacity.txt](scripts/adio_ampacity.txt).

Odd ADIO necks and the PWR_OUT pours were not rewritten. The board file was not edited. Outline stays **(−32, −40)–(142, 162)**. F1 stays open. There is still no SENSOR_GND pour.

| Path | Series neck | 20 °C need |
|------|-------------|------------|
| ADIO1 | 1.754 + 1.760 mm = 3.51 mm, no via | 3.47 mm |
| ADIO3 | 3.80 mm B.Cu under PWR_OUT2 east | 3.47 mm |
| ADIO5 | 3.80 mm B.Cu under PWR_OUT2 east | 3.47 mm |
| ADIO7 | 3.80 mm B.Cu (F ends at the PWR_OUT3 column) | 3.47 mm |
| ADIO2, 4, 6, 8 | 0.60 + 0.60 mm = 1.20 mm after the fanout search | 3.47 mm |
| PWR_OUT1–4 | unchanged 16.72 mm class pours | 16.72 mm |

Vias do not help: the SuperSeal pads are PTH on both layers. Moving the even drivers, opening a south or east corridor, or growing the board does not widen the door, which is upstream of that copper. Giving NC pins 2 and 9 to one even net, and pin 25 to another, can open ADIO2 or ADIO4 (not both) and ADIO8. ADIO6 stays at 1.20 mm even if it takes every NC pin. That reassignment was not applied; the Razor pin map is unchanged. Parallel 0.60 mm slots were not poured.

| Issue | Before | After |
|-------|-------:|------:|
| shorting_items / crossings / clearance / courtyard / padstack / mask bridge | 0 | **0** |
| unconnected_items | 184 | **184** |
| Board copper edited | — | **no** |

`kicad-cli` 8.0.9 numbers are the odd-pour pass. This pass did not change `pdmrazora.kicad_pcb`. No gerbers. `scripts/cut_crossings_sexp.py` was not replayed.

## Previous commit — ADIO 8 A pours

ADIO1, ADIO3, ADIO5, and ADIO7 now have a continuous J1-to-driver pour at the IPC-2221A 1 oz / 20 °C line for 8 A. ADIO2, ADIO4, ADIO6, and ADIO8 stay open: each SuperSeal exit is a 0.60 mm aperture (F+B = 1.20 mm). Coordinates, the width table, and the footprint moves: [scripts/adio_ampacity.txt](scripts/adio_ampacity.txt). Applicator: `scripts/adio_ampacity.py` (run only from a clean `pdmrazora.kicad_pcb`).

Outline stays **(−32, −40)–(142, 162)**. HP zones were not rewritten. F1 stays open, the post-fuse feeder stays **(84.80, 23.40)–(101.70, 29.20)**, and there is still no SENSOR_GND pour. 80 A peak on the HP outs stays pour plus the existing F.Mask hatch.

| Path | Before | After, series neck | 20 °C need |
|------|--------|--------------------|------------|
| ADIO1 | open | 1.754 + 1.760 mm = 3.51 mm, no via | 3.47 mm |
| ADIO3 | open | 3.80 mm B.Cu under PWR_OUT2 east | 3.47 mm |
| ADIO5 | open | 3.80 mm B.Cu under PWR_OUT2 east | 3.47 mm |
| ADIO7 | open | 3.80 mm B.Cu (F ends at the PWR_OUT3 column) | 3.47 mm |
| ADIO2, 4, 6, 8 | open | blocked, 0.60 mm slot, F+B 1.20 mm | 3.47 mm |
| PWR_OUT1–4 | 16.72 mm class | same pours, same filled cross-sections | 16.72 mm |

J3 moves to **(−14, 108)**. U11, U13, U15, and U17 form a column at x=84.8 (y=82, 91, 100, 109, rotation 0, OUT east). U12 and U14 park in the south reserve at y=146 and y=154. C20, C40, and R20 move off the new spurs. U16 and U18 stay. The south reserve is 25 mm tall, so it holds the two parked drivers; the 3.47 mm copper uses the east margin and a via-free B.Cu underpass of PWR_OUT2.

| Issue | Before | After |
|-------|-------:|------:|
| shorting_items / crossings / clearance / courtyard / padstack / mask bridge | 0 | **0** |
| unconnected_items | 183 | **184** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged | no | **no** |
| In1.Cu count | 181 | **181** |

Unconnected is one higher because 172 foreign tracks were removed where they crossed the new zones (no PWR_OUT copper) and the moved parts left their old GND and signal copper. The four odd power paths themselves dropped from 7 open items to 1: the remaining item on each is a sense pad on the y=56.20 resistor row (R201, R203, R205, R207), which is not the 8 A neck. `kicad-cli` 8.0.9, `--severity-error`.

## Previous commit — ampacity floorplan (174×202)

The 109×98 packing cannot hold a 16.72 mm HP neck or a 3.47 mm ADIO neck. This pass grows the outline and shifts M1000 and the west HP drivers so PWR_OUT1–4 have a continuous pour at the IPC-2221A 1 oz / 20 °C line. J1, J2, J3, and F1 stay put. Netclasses are unchanged (HP_OUT 16.72, ADIO_OUT 3.47, VBAT 16.72). Coordinates and the before/after table: [scripts/floorplan_ampacity.txt](scripts/floorplan_ampacity.txt). Applicator: `scripts/floorplan_ampacity.py` (run only from a clean `pdmrazora.kicad_pcb`).

Outline **(0, 0)–(109, 98)** becomes **(−32, −40)–(142, 162)**: **109×98 → 174×202 mm** (+65 mm wide, +104 mm tall). M1000 moves (−30, 0) to (−28, 66). Its board keepout and the footprint keepout both move with it and are inflated to **(−29.1, 24.8)–(15.4, 67.1)** so edge pads stay inside the pour ban. U1 +10 mm, U3 +12 mm. A handful of passives leave the new corridors (listed in the floorplan note). EMI split is unchanged: the module still ends west of the SuperSeal courtyard.

80 A peak is still not a trace (~83 mm). It stays pour plus F.Mask solder-blob openings on the HP pours (352 strokes, was 358). F1 is not bridged: the post-fuse feeder is now **(84.80, 23.40)–(101.70, 29.20)**, 16.90 mm, with the same Y gap. No SENSOR_GND pour. No gerbers. `scripts/cut_crossings_sexp.py` was not replayed.

Series necks below are filled-zone cross-sections. F and B legs on the same path add. A 0.30 mm via drill is subtracted once per layer it pierces. SuperSeal pads are 2.0 mm and the PROFET OUT clusters are ~3.3 mm tall; those pad interfaces are not the 16.72 mm neck.

| Path | Before (audit) | After, series neck | 20 °C need |
|------|----------------|--------------------|------------|
| PWR_OUT1 | 0.20 mm | 8.55 + 8.60 mm hole bypass, then 16.72 mm | 16.72 mm |
| PWR_OUT2 | 0.20 mm | 16.72 mm column, band, and east drop | 16.72 mm |
| PWR_OUT3 | 0.20 mm | 18.22 mm gallery − 0.30 drill, 19.80 mm B drop − 0.30, 19.80 mm F landing − 0.60, then 16.72 mm | 16.72 mm |
| PWR_OUT4 | 0.20 mm | (8.70 − 0.30) mm F+B = 16.80 mm west leg, then 17.80 − 0.30 mm top band and 16.72 mm east | 16.72 mm |
| ADIO6 | 0.15 mm, complete | removed | 3.47 mm |
| ADIO1–5, 7, 8 | not routed | still open | 3.47 mm |
| VBAT post-fuse | 17.5 mm zone | 16.90 mm zone, F1 gap open | 16.72 mm |

ADIO was not re-poured. The SuperSeal pin gaps are 1.0 mm, and J3 sits on the U16 OUT column, so a 3.47 mm ADIO pour cannot leave the connector. The south margin under the PWR_OUT2 band (y=136.72 to the edge at 162) is left clear for that routing later.

| Issue | Before | After |
|-------|-------:|------:|
| shorting_items / crossings / clearance / hole / courtyard / padstack / mask bridge | 0 | **0** |
| unconnected_items | 46 | **183** |
| Pour verts inside M1000 keepout | 0 | **0** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged | no | **no** |
| F.Mask drawings on PWR_OUT | 358 | **352** |
| In1.Cu count | 181 | **181** |

Unconnected rose because the old 0.15–0.20 mm HP and ADIO tracks were deleted, M1000 wall tracks that left the module were dropped, and the moved passives are no longer on their old copper. By net: GND 46, ADIO1–8 ×7 (56), SENSOR_5V 10, VBAT 6 (the fuse gap is still in there), plus the signal nets that used to ride the deleted copper. `kicad-cli` 8.0.9, `--severity-error`.

## Previous commit — track-width audit and post-fuse VBAT feeder

Copper weight is not in the board file (only `(thickness 1.6)`). Widths below use **IPC-2221A external, 1 oz / 35 µm**, pass line **≤20 °C** (top of the 10–20 °C band). 25 A needs **16.72 mm**; 8 A needs **3.47 mm**. The 8–12 mm guess matches 2 oz, which this file does not specify. Full table: [scripts/track_width_audit.txt](scripts/track_width_audit.txt).

HP and ADIO tracks that are already routed stay at 0.15–0.20 mm along the long runs. The corridor beside each of those runs is already at 0.20 mm clearance (J3 pad, the other channel, the board edge, M1000). Widening them to 16.7 mm or 3.5 mm needs a layout change, so those tracks were not moved. 80 A peak needs ~83 mm and is not a continuous width; the 358 F.Mask openings on `PWR_OUT` are still there. Fifteen openings that were 0.15 mm on 0.50–0.70 mm copper are now copper−0.08 mm.

The one neck that was a track inside a wide pour is the post-fuse VBAT entry. F1.2 used to leave on a **2.0 mm** F.Cu strap (~5 A). A priority-2 F.Cu zone `VBAT_post_fuse_feeder` at **(90.5, 23.4)–(108.0, 29.2)** fills **17.5 mm** (~26 A at 20 °C, about 19 °C at 25 A) and joins the existing pour, which is already ~53 mm wide at y=28. It does not touch the pre-fuse pour or F1.1. B.Cu there is the GND return and was left alone. The pre-fuse pour (about 16 mm F + 17 mm B at x=98.5, ~41 A) and the y=55 pour neck (7.5 mm F + 8.0 mm B at x≈99–106) still cannot carry the 150 A fuse.

Netclasses `HP_OUT` / `ADIO_OUT` / `VBAT` now default new routes to 16.72 / 3.47 / 16.72 mm. Existing vias stay 0.6 / 0.3 mm; a 0.30 mm drill is ~0.7 mm of 1 oz and is called out as a neck, not enlarged.

| Issue | Before | After |
|-------|-------:|------:|
| shorting_items / crossings / clearance / hole / courtyard / padstack | 0 | **0** |
| unconnected_items | 46 | **46** |
| Pour verts inside M1000 keepout | 0 | **0** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged | no | **no** |
| F.Mask drawings on PWR_OUT | 358 | **358** |
| Post-fuse VBAT entry width | 2.0 mm track | **17.5 mm** F.Cu zone |

`kicad-cli` 8.0.9, `--severity-error`. No gerbers. `scripts/cut_crossings_sexp.py` was not replayed. No footprint moves.

## Previous commit — ADIO rest attempt (no copper kept)

Does not move the outline, AUX origin, EMI split, bobbins, or any footprint. `scripts/cut_crossings_sexp.py` was not replayed. No SENSOR_GND pour. F1 is not bridged. No gerbers: unconnected stays **46**, still more than the fuse gap plus the M1000 keepout.

One serious attempt to replicate the ADIO6 pattern (local wall jog → B.Cu spine → via on driver F.Cu → B.Cu pour keepout → GND stitch) for ADIO1,2,3,4,5,7,8. Candidates that closed an ADIO ratsnest always opened at least one GND island (ADIO5 also grew VBAT 33→34), so nothing was kept. Stopped; see mm blockers below.

[F.Cu / B.Cu overview](scripts/copper_fill_overview.png). [Neck crop with open ADIO ends](scripts/adio_rest_blockers.png) — yellow ADIO, red keepout boxes, ADIO6 spine annotated. [ADIO6 reference](scripts/neck_adio6.png). Report: [scripts/drc_109.txt](scripts/drc_109.txt). Notes: [scripts/adio_rest_blockers.txt](scripts/adio_rest_blockers.txt). Harness: `scripts/land_adio_rest.py`.

| Issue | PR #17 / main `045cf4b` | After this pass |
|-------|------------------------:|----------------:|
| shorting_items | 0 | **0** |
| tracks_crossing | 0 | **0** |
| clearance | 0 | **0** |
| hole_near_hole | 0 | **0** |
| solder_mask_bridge | 0 | **0** |
| courtyards_overlap | 0 | **0** |
| padstack_invalid | 0 | **0** |
| unconnected_items | 46 | **46** |
| Pour verts inside M1000 keepout | 0 | **0** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged by pour | no | **no** |
| Footprints moved | 0 | **0** |
| Tracks / vias | 1297 / 207 | **1297 / 207** |
| F.Mask drawings on PWR_OUT | 358 | **358** |

| Net group | PR #17 | After this pass |
|-----------|-------:|----------------:|
| GND | 23 | **23** |
| SENSOR_5V | 3 | **3** |
| VBAT | 10 | **10** |
| ADIO1–8 | 7 | **7** (ADIO6 only) |
| IGN_SW / IN_AUX4 / OUT_PWM8 | 3 | **3** |

### mm blockers (why ADIO6 did not generalize)

| Net | Geometry | Blocker |
|-----|----------|---------|
| ADIO2 | Bus to (70.8, 80.6) and B spine to y=62 clear. F landing ~**(71.8, 52.0)** | `SENSOR_5V` y=56.25 (~0.42 mm off col), `OUT_IO7` at x=71.2, `OUT_IO6`/`OUT_PWM2`/`IN_MAP3`/`IN_O2S`/`OUT_IO8`. F stub to y=62 hits ADIO6/ADIO5 F copper. |
| ADIO4 | Column x=23.7 at (23.7, 73) | `IN_RES3` via **(23.2, 76.0)**: center dist **0.50 mm**, need **0.525 mm** (short **0.025 mm**). Trial via nudge to 23.05 opens south bus to x≈72; ADIO6 keepout/J3 then block U14. |
| ADIO8 | Bus (72.0, 82.0); east at y=82 only to x=73 (J3) | No clear `(73→95.8)` row in y=70–84. Vertical x=95.8 blocked y=78–70 (`IN_RES3`/`OUT_PWM2`/`IN_RES1`). East-skirt BFS reaches U18 but cuts B-only GND ~**(98,54)–(103,62)** with no F pour to stitch → unconnected does not drop. |
| ADIO5 | BFS pin (42.3, 46.5)→via (64.2, 60.8) exists | Keepout+stitch closes ADIO5 but **VBAT islands 33→34**, unconnected 46→47. |
| ADIO1/3/7 | Odd J1 pins | No BFS to driver copper within 400k expansions. |
| Secondary | C101/C102/R101/U15/U16/U18 GND; IGN_SW; IN_AUX4; OUT_PWM8; SENSOR_5V R201/R205 | No pad∩B-pour via that drops count; long-haul nets not opened this pass. |

### Still open

Same 46 as PR #17. No gerbers.

## Previous commit — open the GND neck and land ADIO6

Does not move the outline, AUX origin, EMI split, bobbins, or any footprint. `scripts/cut_crossings_sexp.py` was not replayed. No SENSOR_GND pour. F1 is not bridged. No gerbers: the leftover is still more than the fuse gap plus the M1000 keepout.

[F.Cu / B.Cu overview](scripts/copper_fill_overview.png) — gold tracks are `PWR_OUT1–4`, yellow on B.Cu is ADIO. [Neck crop](scripts/neck_adio6.png) — yellow is the ADIO6 spine. [R10 stitch](scripts/r10_stitch.png) — the B.Cu tie from R10.1 to the C10 via. [C105 / C106 / C107](scripts/in_res2_c105.png) — the widened channel and the three vias. [Exposed HP copper](scripts/hp_mask_openings.png) — gold is F.Cu, red is the F.Mask opening. Mask drawings on those nets stayed at **358**. Openings were not covered.

`kicad-cli pcb drc` **8.0.9**, `--severity-error`, `--units mm`. Report: [scripts/drc_109.txt](scripts/drc_109.txt). Edits: `scripts/open_neck.py`, `scripts/widen_in_res2.py`, `scripts/stitch_pads.py`. Rebased onto main `b044550` (PR #16 squash).

| Issue | main `b044550` | After this pass |
|-------|---------------:|----------------:|
| shorting_items | 0 | **0** |
| tracks_crossing | 0 | **0** |
| clearance | 0 | **0** |
| hole_near_hole | 0 | **0** |
| solder_mask_bridge | 0 | **0** |
| courtyards_overlap | 0 | **0** |
| padstack_invalid | 0 | **0** |
| unconnected_items | 51 | **46** |
| Pour verts inside M1000 keepout | 0 | **0** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged by pour | no | **no** |
| Footprints moved | 0 | **0** |
| Tracks / vias | 1273 / 201 | **1297 / 207** |
| F.Mask drawings on PWR_OUT | 358 | **358** |

Against the pre-#16 main (`6c243d8`, 64 unconnected): hard DRC rows stay 0, unconnected is 64 → 46, mask openings stay 358.

### What changed

The hop from the ADIO6 bus at (66.0, 81.4) onto U16 crosses the B.Cu GND neck and would seal the pour between the M1000 keepout (south edge y=65.9) and the y≈81 buses. The column that reaches the driver pad is x=72.4, and OUT_IO7 was using it.

OUT_IO7 B.Cu (79.2, 62.4)–(71.2, 62.4) and (71.2, 62.4)–(71.2, 59.6), both width 0.20, are replaced by (79.2, 62.4)→(73.6, 62.4)→(73.6, 61.4)→(71.2, 61.4)→(71.2, 59.6), still width 0.20. That leaves x=72.4 clear down to the existing F.Cu ADIO6 copper at y=62.0.

ADIO6 then runs B.Cu (66.0, 81.4)→(72.4, 81.4)→(72.4, 62.0), via 0.50/0.30 at (72.4, 62.0), and a 0.15 mm F.Cu tie to (72.8, 62.0). A B.Cu-only pour keepout covers (71, 63)–(75, 81) so the spine does not leave a pour sliver. Tracks, vias, and pads are still allowed there. A GND via 0.50/0.30 at (68.6, 79.0) sits in both the cut-off B pour and the F.Cu pour around J3, so the island ties back through the J3 PTH. The pair diff of the DRC report is one line: the ADIO6 ratsnest is gone. GND stays 26 and VBAT stays 10.

IN_RES2 was a 0.60 mm channel. OUT_PWM2 B.Cu (48.4, 54.8)–(92.0, 54.8) now jogs to y=55.15 between x=81.40 and x=90.8 (still 0.25 mm clear of OUT_IO8 at y=55.60). IN_O2S2 B.Cu (81.6, 54.0)–(92.8, 54.0) jogs to y=54.68 between x=82.15 and x=90.2. Via 0.50/0.30 at (89.22, 54.05) sits on C107.1, and a 0.15 mm B.Cu tie drops to the stub at y=53.20. The same slot then takes GND vias on C105.2 (82.775, 54.05) and C106.2 (86.775, 54.05), each with a 0.15 mm B.Cu tie down to the existing run at y=52.40.

R10.1 was walled into a 0.60 mm B.Cu slot, so the pour never reached the pad. C10.2 was already on that pour through the via at (63.175, 76.20). IN_O2S B.Cu moves to y=75.90 between x=56.8 and x=58.35, and IN_RES2 B.Cu moves to y=77.10 between x=56.45 and x=58.45. Via 0.50/0.30 at (57.375, 76.48) sits on R10.1, and a 0.15 mm B.Cu tie runs to the C10 via. VBAT island count stays 33. Taken together, the two jogs also move one B.Cu GND ratsnest anchor to the zone corner (0.8, 0.8). Each jog by itself does not.

| Net group | main `b044550` | After this pass |
|-----------|---------------:|----------------:|
| GND | 26 | **23** |
| SENSOR_5V | 3 | **3** |
| VBAT | 10 | **10** |
| ADIO1–8 | 8 | **7** (ADIO6 closed) |
| IGN_SW / IN_AUX4 / OUT_PWM8 | 3 | **3** |
| IN_RES2 | 1 | **0** |

### Still open

| Count | What it is |
|------:|------------|
| 23 | GND. **11** are M1000 keepout F/B pairs, and one more is the keepout pair between the pads at (44.20, 65.00) and (44.20, 59.35). C10.2, R10.1, C105.2, and C106.2 are on the pour. Still open: C101.2, C102.2, R101.1, U15.1, U16.1, U18.1, track-to-track islands, and one B.Cu zone fragment anchored at (0.8, 0.8). A via on the open pads does not also land in the pour. |
| 10 | VBAT. One is the intentional fuse gap: pre-fuse zone anchor (68.5, 1.0) vs post-fuse (54.5, 27.5). One is M1000.N27 (18.50, 26.20). The other eight are post-fuse islands. Not bridged. |
| 7 | ADIO1, ADIO2, ADIO3, ADIO4, ADIO5, ADIO7, ADIO8. ADIO6 is on the driver. ADIO2 can reach (70.8, 80.6) on B.Cu and has a legal via on its F.Cu copper at (72.3, 52.0), but OUT_IO7's via at (71.2, 59.6), SENSOR_5V at y=56.2, OUT_PWM2 at y=54.8, IN_MAP3 at y=54.0, and IN_O2S at y=52.8 close every column before that via. ADIO8 cannot step east of x=72 at y=82 (J3 pad, then the ADIO6 spine). ADIO4 cannot leave (23.7, 73): IN_RES3 occupies x=23.2. The odd pins are still on J1. |
| 3 | SENSOR_5V edges. R201.1 and R205.1 (R205 is in two edges). R202 and R206 are already tied. No via lands on R201 or R205; ADIO1 / IN_MAP2 sit on the R201 pad and ADIO4 / ADIO5 sit on R205. |
| 1 | IGN_SW. J1.4 (34.30, 46.50) to R1.1 (55.175, 18.50). The pin's pocket is only y=44.0–48.3. B.Cu at x=1.2 is clear from y=40 to y=18, west of M1000, but the module's west pad row at x≈2.3 is on a 1.0 mm pitch with a 0.40 mm copper gap, so nothing enters that column. PWR_OUT4 at x=16.5 and the SENSOR_GND bypass at x=12 block the straight west run. PWR_OUT copper was not moved. |
| 1 | IN_AUX4. M1000.S10 (32.70, 65.70) to C40.1 (96.825, 32.20). |
| 1 | OUT_PWM8. M1000.E28 (44.00, 49.60) to the B.Cu track at (90.00, 47.80). The reachable pocket is only x=43.6–45.2, y=49.3–64.4. |

No gerbers. 46 unconnected is more than the fuse gap plus the M1000 keepout.

## Previous commit — corridors and pour stitches

Does not move the outline, AUX origin, EMI split, bobbins, or any footprint. `scripts/cut_crossings_sexp.py` was not replayed. No SENSOR_GND pour. F1 is not bridged. No gerbers: the leftover is still more than the fuse gap plus the M1000 keepout.

[F.Cu / B.Cu overview](scripts/copper_fill_overview.png) — gold tracks are `PWR_OUT1–4`, yellow on B.Cu is the ADIO west exit. [Exposed HP copper](scripts/hp_mask_openings.png) — gold is F.Cu, red is the F.Mask opening. Mask drawings on those nets stayed at **358**. Openings were not covered.

`kicad-cli pcb drc` **8.0.9**, `--severity-error`, `--units mm`. Report: [scripts/drc_109.txt](scripts/drc_109.txt). Router: `scripts/open_corridors.py`.

| Issue | PR #15 | After this pass |
|-------|-------:|----------------:|
| shorting_items | 0 | **0** |
| tracks_crossing | 0 | **0** |
| clearance | 0 | **0** |
| hole_near_hole | 0 | **0** |
| solder_mask_bridge | 0 | **0** |
| courtyards_overlap | 0 | **0** |
| padstack_invalid | 0 | **0** |
| unconnected_items | 64 | **51** |
| Pour verts inside M1000 keepout | 0 | **0** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged by pour | no | **no** |
| Footprints moved | 0 | **0** |
| Tracks / vias | 1232 / 190 | **1273 / 201** |
| F.Mask drawings on PWR_OUT | 358 | **358** |

### What changed

The SENSOR_GND B.Cu spine at x=38.40 (y=43.20–55.60, width 0.20) is gone, along with the three vias that tied it (38.00, 43.20), (39.20, 55.60), (43.20, 61.20). Replacement is a 0.15 mm B.Cu bypass from J1.12 at (36.60, 41.60) west to x=12.00, south to (12.00, 63.60), and a 0.50/0.30 via onto the existing F.Cu SENSOR_GND bus at y=63.60. The F.Cu J1.6↔J1.12 ties stay. SENSOR_GND is still tracks and vias only.

The F.Cu SENSOR_5V spine at x=38.40 (y=46.40–62.00) moved with it. Replacement is a B.Cu drop at x=10.00 from the existing F.Cu run at y=43.60 onto the F.Cu bus at y=62.40, with a via at each end.

That opens the 1.00 mm slot between the middle SuperSeal column (x=36.80) and the west ADIO column (x=39.80). ADIO2, ADIO4, ADIO6, and ADIO8 each leave their pin on B.Cu through their own column gap, then a private lane and a private S-row passage down to y=73. ADIO8 continues to (72.0, 82.0) and ADIO6 to (66.0, 81.4). Those buses stay at y≥80 so they do not cross the GND pour neck at y≈76–78. The last hop from that bus onto the driver copper does cross the neck (or the east board edge) and isolates a GND island, so it is not in this board. ADIO1/3/5/7 are still on their J1 pins. All eight ADIO ratsnest lines remain; the west pins now have a legal exit.

GND stitches, all clearance-checked, no footprint moves:

| Copper | What it ties |
|--------|----------------|
| B.Cu (77.20, 52.40)→(78.90, 51.00) plus via (77.175, 52.40) | R104.1 onto the B pour |
| F.Cu (90.80, 54.30)→(92.60, 53.60)→(92.60, 52.40) | C107.2 |
| F.Cu (66.80, 54.30)→(69.20, 52.40) | C101.2 |
| F.Cu (74.80, 54.30)→(73.90, 55.10)→(72.40, 55.10)→(72.50, 53.60)→(72.90, 51.70) | C103.2 |
| F.Cu (69.90, 50.40)→(69.90, 52.20) | U11.1 |
| Via in pad, ring already in the B pour | R2.2 (56.00, 20.675), C104.2 (78.775, 54.225), C1.2 (63.50, 6.55), D1.2 (106.00, 19.85), R20.1 (100.975, 77.00), C20.2 (98.375, 77.00) |
| Via on the south edge of the pad | C10.2 (63.175, 76.20). Joins a pour island. The pad itself stays on the ratsnest. |
| F.Cu (94.15, 6.20)→(103.90, 6.20) plus via (103.90, 6.20) | C2.2, via ring already in the B pour |
| Via (94.775, 54.30) plus B.Cu (94.775, 54.30)→(98.20, 54.30)→(98.20, 52.10)→(97.90, 51.80)→(91.90, 51.80) | C108.2 onto the B pour |

A longer F.Cu stitch from R102 down to y≈46 closed two more GND pads and opened a VBAT island. It is not in this board. VBAT stays at 10.

SENSOR_5V: via at R202.1 (69.175, 56.20) and a B.Cu track to (73.60, 56.30). The other pull-up pads in that row do not accept a via.

| Net group | PR #15 | After this pass |
|-----------|-------:|----------------:|
| GND | 38 | **26** |
| SENSOR_5V | 4 | **3** |
| VBAT | 10 | **10** |
| ADIO1–8 | 8 | **8** |
| IGN_SW / IN_AUX4 / IN_RES2 / OUT_PWM8 | 4 | **4** |

### Still open

| Count | What it is |
|------:|------------|
| 26 | GND. **13** are M1000 keepout F/B pairs. The other **13** are 10 carrier pads the pour still misses (C10.2, C101.2, C102.2, C105.2, C106.2, R10.1, R101.1, U15.1, U16.1, U18.1) plus three track-to-track islands. No via inside those pads lands in the pour. R101 has an F.Cu path through y≈46 that reaches a pour via and drops GND by one, and it opens two VBAT islands, so it is not routed. |
| 10 | VBAT. One is the intentional fuse gap: pre-fuse zone anchor (68.5, 1.0) vs post-fuse (54.5, 27.5). One is M1000.N27 (18.50, 26.20). The other eight are post-fuse islands. |
| 8 | ADIO1–8. West pins have a B.Cu exit to y=73 and, for ADIO6/ADIO8, a bus at y≥80. The driver copper is north of the pour neck at y≈76–78. A track across that neck isolates GND, so the eight J1-to-driver lines stay open. |
| 3 | SENSOR_5V. R201.1, R205.1, R206.1 at y=56.20. R202 is tied. Pad centers other than R202 are not a legal via. |
| 1 | IGN_SW. J1.4 (34.30, 46.50) to R1.1 (55.175, 18.50). |
| 1 | IN_AUX4. M1000.S10 (32.70, 65.70) to C40.1 (96.825, 32.20). |
| 1 | IN_RES2. C107.1 (89.225, 54.30) to the B.Cu track at (88.00, 53.20). The 0603 neighborhood has no same-layer exit. |
| 1 | OUT_PWM8. M1000.E28 (44.00, 49.60) to the B.Cu track at (90.05, 47.85). |

No gerbers. 51 unconnected is more than the fuse gap plus the 13 keepout pairs.

IGN_SW still cannot leave J1.4. On F.Cu the pin stops at the SENSOR_5V run y=43.60, and the pocket north of that run stops on the PWR_OUT3/PWR_OUT4 copper at y≈37. On B.Cu the north row of M1000 (y≈26.4) and the driver wall at x≈44 close the other way around. IN_RES2 is a 0.60 mm channel between IN_O2S2 (y=54.00) and OUT_PWM2 (y=54.80); a via needs 0.90 mm, and a jog of either track does not both clear and still reach the B.Cu stub at y=53.20. IN_AUX4 on B.Cu reaches about x=58 after 80k cells and has not found the copper at (96.8, 32.2). OUT_PWM8 on F.Cu is a slot along the keepout edge, x=43.6–45.2, y=49.3–64.4, and the B.Cu side of that slot drains in a few hundred cells.

## Previous commit — carrier ratsnest on the 109×98 board

Does not move the outline, AUX origin, EMI split, bobbins, or any footprint. `scripts/cut_crossings_sexp.py` was not replayed. No SENSOR_GND pour. F1 is not bridged. No gerbers: the leftover is still more than the fuse gap plus the M1000 keepout.

[F.Cu / B.Cu overview](scripts/copper_fill_overview.png) — gold tracks are `PWR_OUT1–4`. [Exposed HP copper](scripts/hp_mask_openings.png) — gold is F.Cu, red is the F.Mask opening. Mask drawings on those nets stayed at **358**. Openings were not covered.

`kicad-cli pcb drc` **8.0.9**, `--severity-error`, `--units mm`. Report: [scripts/drc_109.txt](scripts/drc_109.txt).

| Issue | PR #14 (109×98) | After this pass |
|-------|----------------:|----------------:|
| shorting_items | 0 | **0** |
| tracks_crossing | 0 | **0** |
| clearance | 0 | **0** |
| hole_near_hole | 0 | **0** |
| solder_mask_bridge | 0 | **0** |
| courtyards_overlap | 0 | **0** |
| padstack_invalid | 0 | **0** |
| unconnected_items | 129 | **64** |
| Pour verts inside M1000 keepout | 0 | **0** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged by pour | no | **no** |
| Footprints moved | — | **0** |
| Tracks / vias | 1008 / 121 | **1232 / 190** |
| F.Mask drawings on PWR_OUT | 358 | **358** |

### What closed

Local layer fixes (a via at the pad, 0.50/0.30) plus short ties inside 3 mm. GND carrier pads got one stitch each onto the B.Cu pour. C1.1 was strapped to the pre-fuse pour. Two post-fuse VBAT slivers were tied. PWR_OUT1–4 were already connected and were not retouched.

| Net group | Before | After |
|-----------|-------:|------:|
| OUT_PWM / OUT_IO | 21 | **1** (OUT_PWM8 ↔ M1000.E28) |
| IN_* | 13 | **2** (IN_AUX4, IN_RES2) |
| ADIO1–8 | 25 | **8** (J1 pins only; driver side is tied) |
| GND | 53 | **38** |
| VBAT | 11 | **10** |
| SENSOR_5V | 5 | **4** |
| IGN_SW | 1 | **1** |

### Still open — geometry, not a search limit

| Count | What it is |
|------:|------------|
| 38 | GND. **13** are M1000 keepout pad pairs (F.Cu vs B.Cu); the pour is not allowed in the keepout. The other **25** are carrier pads the B pour does not reach: the sense RC row (C101–C108, R101–R104, U11/U15/U16/U18 pin 1), R10/C10, R20/C20/U2.1, and the north stubs R2.2 / C1.2 / C2.2 / D1.2. Router notes: C105.2 (82.78, 54.30) is 3.08 mm from the pour cell (85.20, 52.40); R104.1 (77.17, 52.40) is 2.28 mm from (78.80, 50.80). A second pass was not run. |
| 10 | VBAT. One is the intentional fuse gap: pre-fuse zone anchor (68.5, 1.0) vs post-fuse (54.5, 27.5). One is M1000.N27 (18.50, 26.20), 36.33 mm from the post pour at (54.80, 27.60); the commit check rejected that path so it does not cross the fuse band (y=23.15–26.05). The other eight are post-fuse zone islands. DRC reports them all at the zone anchor (54.5, 27.5). C1.1 is connected. |
| 8 | ADIO1–8, the J1 pins only. Columns x=39.80 and x=42.30 sit east of the SENSOR_GND spine (B.Cu x=38.40, y=43.20–55.60, width 0.20). That spine blocks a west exit until y≈56. The band south of it (y=56.8–59.9, x=32–41) is 3.1 mm tall, but the pad maze east of the spine has one southbound opening. Routing ADIO1 through it (x=40.6–42.3, y=52.5–59.1) leaves ADIO2–7 with no path. All eight J1 pins were left open so that opening stays unused. |
| 4 | SENSOR_5V. The pull-up row is y=56.20, x=65.175 / 69.175 / 77.175 / 81.175 (R201, R202, R204, R205 pin 1), pitch 4.00 mm. Search stopped at 700k expansions on R201.1→R202.1 and on the track at (77.20, 56.20)→R205.1. |
| 1 | IGN_SW. J1.4 (34.30, 46.50) has no free B.Cu cell within 0.8 mm. A* does not reach the north shelf (42.0, 24.8) or the east alley (44.8, 32.0). R1.1 is (55.175, 18.50), on the far side of the same spine. |
| 1 | IN_AUX4. C40.1 (96.83, 32.20) to M1000.S10 (32.70, 65.70), 72.35 mm. Search stopped at 700k. |
| 1 | IN_RES2. C107.1 (89.22, 54.30) to the B.Cu tracks at y=53.20 (x=88.00 / 90.80). The neighborhood exhausts in 325 expansions: a same-layer exit does not clear SENSOR_5V and the neighboring 0603. |
| 1 | OUT_PWM8. Track end (90.00, 47.80) to M1000.E28 (44.00, 49.60), 46.04 mm. Search stopped at 700k. The east pad row is a 0.60 mm wall; the south slots are the long way around and were left for the ADIO pins. |

M1000 S-row passages that do reach y=76 on B.Cu, if a later pass needs them: x=18.9, 20.1, 21.3, 22.5, 23.7, 24.9, 26.1. Each waist is one 0.10 mm cell in a 0.60 mm copper gap, so one 0.15 mm track. x=45.6 is east of that wall and is not reachable from the pin field. J3 at (80, 86.5), radius 8 mm, pinches a south bus at x=82 down to y=73.0–74.2 (1.2 mm) plus a 0.4 mm sliver at y=78.0–78.4.

## Previous commit — 109×98 symmetric drivers

Edge.Cuts grew **5 mm on each axis**: **104×93 → 109×98 mm**. AUX origin is `(0, 98)` (bottom-left). This stays Razor-class. It does not return to 150×130. `scripts/cut_crossings_sexp.py` and the old 150×130 long-haul routers were not replayed. No SENSOR_GND pour. F1 is not bridged by a pour. No gerbers: the leftover ratsnest is more than the fuse gap plus the M1000 keepout.

[F.Cu / B.Cu overview](scripts/copper_fill_overview.png) — gold tracks are `PWR_OUT1–4`. [Exposed HP copper](scripts/hp_mask_openings.png) — gold is F.Cu, red is the F.Mask opening over that copper.

`kicad-cli pcb drc` **8.0.9**, `--severity-error`, `--units mm`. Report: [scripts/drc_109.txt](scripts/drc_109.txt).

| Issue | 104×93 main | After 109×98 |
|-------|------------:|-------------:|
| shorting_items | 0 | **0** |
| tracks_crossing | 0 | **0** |
| clearance | 0 | **0** |
| solder_mask_bridge | 0 | **0** |
| courtyards_overlap | 20 | **0** |
| padstack_invalid | 22 | **0** |
| unconnected_items | 60 | **129** |
| Outline | 104×93 | **109×98** |
| Pour verts inside M1000 keepout | — | **0** |
| SENSOR_GND pours | 0 | **0** |
| F1 bridged by pour | no | **no** |

### Outline and EMI split

| Item | Value |
|------|--------|
| Edge.Cuts | **109 × 98 mm**, origin top-left, Y down |
| AUX origin | **(0, 98)** |
| Power-field centerline | vertical **x = 80** (drivers mirror about this line) |
| EMI wall | J1 vertical SuperSeal stays at **(48.8, 46.5) rot 90** |
| MCU | M1000 stays at **(2, 66) rot 0**, west of the wall |
| Bobbins | J2 VBAT+ **(80, 12)** north edge, J3 GND **(80, 86.5)** south edge. Not re-paired. Not on the M1000 side. |

### Symmetric driver map

Mirrored about x=80. West parts are rot 0 (OUT faces west, toward the connector). East parts are rot 180 (OUT faces east). North HP row feeds the north-end SuperSeal pins; south HP row feeds the south-end pins, so the same-layer paths do not have to cross.

| Ref | Net | Before (104×93) | After (109×98) |
|-----|-----|-----------------|----------------|
| J2 | VBAT | (92, 11) rot 0 | **(80, 12) rot 0** |
| J3 | GND | (92, 82) rot 0 | **(80, 86.5) rot 0** |
| F1 | fuse | (58, 18) rot 0 | **(100, 15) rot −90** |
| U3 | PWR_OUT3 | (80, 53) rot 90 | **(66, 39.2) rot 0** |
| U4 | PWR_OUT4 | (96, 53) rot 90 | **(94, 39.2) rot 180** |
| U1 | PWR_OUT1 | (80, 40) rot −90 | **(66, 69.4) rot 0** |
| U2 | PWR_OUT2 | (96, 40) rot −90 | **(94, 69.4) rot 180** |
| U11–U14 | ADIO1–4 | y=69.5, x=52/60/68/76 rot 0 | **y=48.5**, x=67.1/75.7 rot **180**, x=84.3/92.9 rot **0** |
| U15–U18 | ADIO5–8 | y=77.5, same x, rot 0 | **y=60.1**, same x and rot rule |

Full before/after list (52 moved footprints): [scripts/layout_109_moves.txt](scripts/layout_109_moves.txt). J1 and M1000 did not move. Courtyard overlaps after the move: **0**.

### M1000 keepout

Hellen mega-mcu144 **0.7** (`hellen-one/modules/mega-mcu144/0.7`). Official keepout in the footprint is local `(0.1, −40) … (42.2, −0.1)`. On this board, with the anchor at (2, 66), that is **(2.1, 26.0)–(44.2, 65.9)**.

The embedded footprint had 22 inner pads (`In1.Cu` / `In2.Cu` stacked pairs, pad number `G`) saved with an empty layer set. Those are restored to the official inner layers, which clears the 22 `padstack_invalid` hits. A board-level rule area on F.Cu and B.Cu disallows copper pour and allows tracks, vias, and pads. After fill, **0 pour vertices** sit inside the keepout. Silk on the footprint already matched the 0.7 outline; it was not redrawn.

### Exposed HP output copper

Nets **PWR_OUT1, PWR_OUT2, PWR_OUT3, PWR_OUT4**. The solder-add copper is **F.Cu**. Every F.Cu segment on those nets has an **F.Mask** opening 0.08 mm narrower than the copper, so the mask does not reach the next net and the current path itself is bare. B.Cu hops are only where the module south-pad wall (0.6 mm gaps) or an existing signal track leaves no 0.20 mm F.Cu corridor; those hops are not mask-opened because there is no top copper there.

| Net | SuperSeal pins | F.Cu (exposed) | B.Cu hop |
|-----|----------------|----------------|----------|
| PWR_OUT1 | J1.14 + J1.20 | 1.2 mm south trunk (55.6, 72.4)–(34.2, 72.4), plus 0.9 mm inside the field; pin fanout up to 2.4 mm | ~8 mm |
| PWR_OUT2 | J1.1 + J1.8 | pin/tab fanout to 2.4 mm and a 1.2 mm piece; the long perimeter run is 0.20–0.70 mm | ~17 mm |
| PWR_OUT3 | J1.7 + J1.13 | pin fanout to 2.4 mm; field run 0.50–0.70 mm, with ~120 mm still at 0.20 mm | ~13 mm |
| PWR_OUT4 | J1.19 + J1.26 | 0.9 mm east trunk along x=107.2 from the OUT pins to y=73.6; pin fanout to 2.4 mm; ~162 mm of the return path stays 0.20 mm | ~11 mm |

All four nets are connected (no `PWR_OUT*` ratsnest). The 0.20 mm lengths are the corridors that will not take a wider track at 0.20 mm clearance. Assemblers can load solder on the exposed F.Cu; the wide sections are the ones that add real copper area.

### Still open (no gerber zip)

| Count | What it is |
|------:|------------|
| 53 | GND. About 14 are M1000 keepout pad pairs the pour is not allowed to fill. The rest are carrier stubs and module pads outside the punched pour. |
| 11 | VBAT. Ten are islands inside the post-fuse pour. One is C1.1, west of the pre-fuse finger. The pre-fuse / post-fuse split at F1 is intentional and is not bridged. D1.1 is strapped into the post-fuse pour only. |
| 25 | ADIO1–8. SuperSeal pins are still open; the 2.0 mm pads on a 2.5 mm pitch do not leave a 0.20 mm exit toward the drivers. |
| 21 | OUT_PWM / OUT_IO. M1000 east pads versus a track on the other copper layer. |
| 13 | IN_* sense and module pins, including C107.1 (`IN_RES2`). The old B.Cu stub from that F-only pad crossed `IN_O2S2` and did not actually connect the pad. It was removed. A same-layer exit does not clear SENSOR_5V and the neighboring 0603. |
| 5 | SENSOR_5V |
| 1 | IGN_SW |

## Previous commit — carrier ratsnest close (stacked on the DRC polish)

Does not undo the polish anchors (U3/U4 at +90°, J1 at x=48.8, D1 at (88, 24), sense RC at y=35.70). That pass held 104×93, J2 north / J3 south, M1000 west. No SENSOR_GND pour. F1 is not bridged. `scripts/cut_crossings_sexp.py` was not replayed. No gerbers.

[F.Cu / B.Cu overview](scripts/copper_fill_overview.png)

`kicad-cli pcb drc` **8.0.9**, `--severity-error`, `--units mm`. Counts below are from that run after the R1 courtyard experiment was reverted (it shorted IN_VIGN).

| Issue | Polish start | After this pass |
|-------|-------------:|----------------:|
| shorting_items | 0 | **0** |
| tracks_crossing | 0 | **0** |
| clearance | 0 | **0** |
| unconnected_items | 75 | **60** |
| courtyards_overlap | 20 | **20** |
| padstack_invalid | 22 | **22** (M1000, left alone) |
| Tracks / vias | 931 / 210 | **1205 / 231** |

SENSOR_GND pours: **0**. Fuse still open (no VBAT segment touches both F1 pads). Placements of U3, U4, J1, D1, R10/C10/R20/C20, J2, J3, M1000, and F1 are unchanged. R1 was trial-nudged +0.37 mm in X to clear the F1 courtyard and moved back: the pad landed on the IN_VIGN track at y=23.2.

One via moved: SENSOR_GND at `(38.4, 55.6)` → `(38.4, 56.4)`, with the back-side spine extended to meet it. That via was the copper that sealed the only 0.20 mm corner out of J1 pin 21. The corner opens; the west corridor it feeds is still walled off from the ADIO driver copper (SENSOR_5V at y=61.7, IGN_SW at y=46.4, M1000 east pads 0.40 mm from the SuperSeal).

### What actually closed

| Net | Change |
|-----|--------|
| IN_RES3 | U18.4 tied to the sense copper. |
| GND | Five carrier stubs joined (U2.1/C20.2, R20.1, R2.2, C2.2, one track stub). DRC GND count 25 → 24 after the earlier stitch had already taken 31 → 25; two carrier stubs remain. |
| SENSOR_5V | M1000 E38 and the R203/R204 pin-1 pair were already on the ratsnest that DRC reports; the new segments did not remove a DRC item. R206.1, R207.1, R208.1 and the x=2.0/2.6 stub are still open. |

### Still open (do not treat as fab-clean)

| Count | What it is |
|------:|------------|
| 22 | M1000 `padstack_invalid`. Not edited. |
| 22 | M1000 GND front/back keepout openings. Not edited. |
| 20 | Courtyard overlaps. The only pair a ≤0.5 mm nudge can separate is F1/R1, and that nudge shorts IN_VIGN. U1/U2 vs the locked sense RC, and J2 vs D1, need more than 0.5 mm. |
| 10 | VBAT zone islands (HP slivers, B alley, ADIO tabs). A 0.22 mm local search from each island does not reach the post-fuse pour without entering the fuse keepout. |
| 1 | VBAT fuse gap. F.Cu strap into D1 vs the B.Cu hop from J2 to F1.1. Left open on purpose. |
| 2 | GND carrier stubs: F track `(57.15, 75.55)` vs via `(55.575, 80.8)`, and B `(79.2, 36.7)` vs F `(76.19, 60.65)`. |
| 4 | SENSOR_5V: R206.1, R207.1, R208.1, and the stub at x≈2 beside M1000. |
| 10 | ADIO1–8. J1 pins 15–17 and 21–24 are still open, plus R205.2 and R206.2. SuperSeal pads are 2.0 mm on a 2.5 mm column pitch (0.5 mm copper gap). A 0.20/0.20 rule cannot leave those pockets toward the drivers. |
| 4 | PWR_OUT1–4, one ratsnest each, across the M1000 north pad wall (0.2 mm gaps from x=2 to x=44.3). |
| 1 | IGN_SW, via `(43.6, 27.6)` vs track `(45.2, 27.6)`, same wall. |
| 6 | IS pins U12.4–U17.4. The inter-package slots are already full of OUT_PWM / ADIO / IN_AUX. IN_RES3 was the one slot with a clearance-legal 0.20 mm path. |

## Previous commit — surgical DRC polish (still not fab-clean)

Floorplan is the split-bobbin nest from PR #10. EMI split was not moved and the bobbins were not re-paired. `scripts/cut_crossings_sexp.py` and the other 150×130 routers were not replayed. Copper for the rotated HP/ADIO/SuperSeal nets was rebuilt in pcbnew from real pad coordinates (`scripts/drc_polish_east.py`).

[F.Cu / B.Cu overview](scripts/copper_fill_overview.png)

`kicad-cli pcb drc` **8.0.9**, `--severity-error`. Counts in [scripts/drc_zonefill.json](scripts/drc_zonefill.json) and [scripts/copper_status.txt](scripts/copper_status.txt).

| Issue | Main (PR #10 fill) | This polish |
|-------|-------------------:|------------:|
| shorting_items | 177 | **0** |
| tracks_crossing | 131 | **0** |
| clearance | 110 | **0** |
| unconnected_items | 87 | **75** |
| solder_mask_bridge | 199 | **0** |
| via_diameter | 73 | **0** |
| drill_out_of_range | 73 | **0** |
| hole_near_hole | 17 | **0** |
| hole_clearance | 18 | **0** |
| courtyards_overlap | 23 | **20** |
| padstack_invalid | 22 | **22** (M1000, left alone) |
| Tracks / vias | 406 / 145 | **931 / 210** |

Pad-pad overlaps after the nudges below: **0**. SENSOR_GND pours: **0**. No VBAT segment touches both F1 pad coppers. A connectivity flood keeps J2 (pre-fuse) on a different island from F1.2 / the post-fuse, HP, and ADIO pours. The one VBAT ratsnest that remains is that fuse gap (F strap into D1 vs the B.Cu hop from J2 to F1.1).

### Placement nudges

Required to separate pad copper. J2, J3, M1000, U1, U2, and the ADIO anchors (U11–U18) did not move.

| Ref | Change |
|-----|--------|
| U3, U4 | Rotation **−90° → +90°**. Anchors `(80, 53)` and `(96, 53)` unchanged. Tabs stay between the bobbins; pins face south so they no longer sit under the U1/U2 tabs. |
| R10, C10, R20, C20 | Y only, `32.00 → 35.70`. X unchanged. Sits in the gap between the north pin row and the tab. |
| D1 | `(80, 28) → (88, 24)`, rotation still 90°. |
| J1 | `(50.00, 46.50) → (48.80, 46.50)`, rotation still 90°. **1.2 mm west** so the SuperSeal PTH columns clear the M1000 east pad wall. |

### Leftovers (do not treat this as fab-clean)

| Count | What it is |
|------:|------------|
| 22 | M1000 `padstack_invalid`. Module artifact. Not edited. |
| 22 | M1000 GND pad, front copper vs back copper. The module keepout punches the pour. |
| 20 | Courtyard overlaps (was 23). U3/U4 now face south; courtyards still meet the sense parts. |
| 10 | VBAT zone-to-zone. Split fill inside the HP zone (including one F island vs the B alley) and inside the ADIO zone. The ADIO pour is cut into per-driver islands by the pin-row tracks. U14's island is tied to the HP pour; the other ADIO tabs are local islands. |
| 1 | VBAT track-to-track. This is the fuse gap: the B.Cu hop from J2 to F1.1 versus the F.Cu strap from the post-fuse pour into D1. Do not connect them. |
| 9 | GND stitch stubs (track-track or track-via) that do not quite meet. |
| 9 | SENSOR_5V. Router joined 4 of 13 pads. Still open: R201–R208 pin 1 and M1000 E38. |
| 12 | ADIO1–8 landings. Mostly a SuperSeal pin (J1.15–17, J1.21–24) or a pull-up (R201.2, R205.2, R206.2) left 0.07–0.5 mm short, plus U13 pins 12–14. |
| 4 | PWR_OUT1–4, one ratsnest each, after the second pass deleted a shorting stub. |
| 1 | IGN_SW, via vs track. |
| 7 | IS pins U12.4–U18.4 (IN_MAP2/3, IN_O2S, IN_O2S2, IN_RES1–3) not tied to the local sense part. |

EN columns stay in the gap west of the M1000 east pads. No new via was dropped on those columns to chase the islands above.

## Previous commit — critical-net copper + zone fill on the split-bobbin floorplan

Mechanical placement from PR #9 is **unchanged** (54 footprints, 104×93 mm, J2 north / J3 south, vertical SuperSeal EMI wall, M1000 west). Old 150×130 / paired-M6 copper scripts were **not** reapplied. `scripts/cut_crossings_sexp.py` was **not** replayed.

[F.Cu / B.Cu zone-fill overview](scripts/copper_fill_overview.png)

| Item | Status |
|------|--------|
| Tracks / vias | **406 / 145** (was 0 / 0 after PR #9 wipe) — +11 GND stitch vias, +6 M6 ring, +13 HP-tab thermal |
| Zones filled | **9** copper pours (GND B full-board, GND F around J3, VBAT F J2 / post-fuse / HP / ADIO, VBAT B J2 / post-fuse / HP alley). Keepout punches M1000. |
| Pad connect | **solid** on VBAT/GND (not thermal spokes) |
| HP VBAT F | `(73,32)–(103,64)` covers TO-263 tabs (north-facing). |
| VBAT B | J2 + post-fuse north islands + east alley `(86,32)–(103,61)` — **stops north of EN** (EN B south-hwys y≥66.7) |
| Fuse | J2 pour **split** from post-fuse pour (F1.1 is not in the island with F1.2 / J2) |
| EN/IS | **Track-connected** (union-find 0). EN exclusive B.Cu MCU–J1 gap columns + pin-south / south-of-J1 highways. IS local F (HP) / B-under-package (ADIO) + F.Cu staircase long-haul to S pads |
| PWR_OUT / ADIO | SuperSeal fanouts east of the pin field except J1 landings; ADIO F-hops the EN B band |
| GND | B.Cu full-board + F.Cu J3 island; carrier GND islands **11 → 0** after stitch+fill. **No SENSOR_GND bond** |
| SENSOR pour | **None** (not present; not added) |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| F1 | **ATO placeholder left** (Jeoff: do not block) |
| Footprints | **54** — placements not moved |

`kicad-cli pcb drc` **8.0.9**. See [scripts/drc_zonefill.json](scripts/drc_zonefill.json) and [scripts/unconnected_leftover.txt](scripts/unconnected_leftover.txt). **Not DRC-clean** — packed-east shorts/crossings remain for human polish.

## Previous commit — split M6 bobbins onto opposite power-field edges

Quintin: *“Split the Vbat & ground bobbins and place them on opposite sides of the board (not on the same side as the m1000) with the drivers inbetween.”*

Placement-only. Dual-bobbin `J2` replaced by `J2` VBAT+ `(92, 11)` and `J3` GND `(92, 82)`. Carrier tracks/vias/filled polygons wiped. That copper is **this** follow-up.

| Item | Status |
|------|--------|
| Outline | **104 × 93 mm** |
| J2 / J3 | North VBAT+ / south GND, 71 mm N–S |
| Tracks / vias | **0 / 0** (intentionally stripped) |
| Zones | **7 unfilled outlines** |
| Footprints | **54** |

## Previous commit — zone fill + M6/HP stitch (104×93 EMI split)

Critical-net copper from the previous commit is **unchanged in plan** (no footprint moves, no 150×130 scripts, F1 ATO left). Pours are now **filled** in pcbnew 8.0.9. No SENSOR pour was added (none existed; SENSOR_GND stays off chassis).

That fill assumed **co-located** east M6 bobbins and was **invalidated** by this floorplan (copper stripped).

| Item | Status |
|------|--------|
| Tracks / vias | **385 / 158** (was 385 / 136) — +10 M6 bobbin vias, +12 HP-tab thermal vias |
| Zones filled | **7** copper pours (GND B full-board, GND F M6−, VBAT F entry/HP/ADIO, VBAT B entry + U1/U2 tab island). Keepout punches M1000. |
| Pad connect | **solid** on VBAT/GND (not thermal spokes) |
| SENSOR pour | **None** (not present; not added) |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Footprints | **53** |

## Previous commit — critical-net re-route on the 104×93 floorplan

Mechanical placement from the previous commit is **unchanged** (53 footprints, 104×93 mm, M6 bobbins, vertical SuperSeal EMI wall, M1000 keepout). Old 150×130 copper scripts were **not** reapplied.

| Item | Status |
|------|--------|
| Tracks / vias | **385 / 136** (was 0 / 0 after the move) |
| EN/IS (HP1–4 + ADIO1–8) | **Connected** (exclusive EN B.Cu south-of-J1 highways + MCU-gap columns; IS local F + B.Cu east-skirt long-haul to S pads) |
| PWR_OUT1–4 / ADIO1–8 | **Connected** to SuperSeal (U1/U2 west of EN band; U3/U4 F-hop; ADIO 0.80 mm columns) |
| VBAT | F.Cu entry spine M6+→F1→C/D + B.Cu east alley to HP tabs; module N27 via **north corridor only** |
| GND | B.Cu full-board pour + sparse local F stubs/vias (no overcrowded east packs); **no SENSOR_GND bond**; M6− F island only |
| CAN / SENSOR_5V / SENSOR_GND / IGN_SW / IN_VIGN | **Connected** (north/east skirt; SENSOR_5V does not traverse the EN field) |
| USB | On-module only (USB-C is on mega-mcu144) — not a carrier leftover |
| J1 courtyard | **39.5 × 29.5 mm** (TE width 39 × catalog vertical D 29). Product-page **39 × 36.5 mm** shroud is on Cmts.User and **does not fit** between M1000 and U1 without moving HP. |
| Via packs (size+0.22) | **0** |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| F1 | **ATO placeholder left** (Jeoff: do not block) |
| Footprints | **53** |

`kicad-cli pcb drc` was **not available** in that agent VM. Geometric H–V scan (not KiCad DRC) still saw same-layer crossings in the packed east/south field. Zone fill + DRC is this follow-up.

See [scripts/unconnected_leftover.txt](scripts/unconnected_leftover.txt).

## Previous commit — mechanical / floorplan redesign (Quintin)

| Item | Status |
|------|--------|
| Outline | **150 × 130 → 104 × 93 mm** (Link Razor class: enclosure 103.6 × 93.4) |
| AUX origin | **(0, 93)** — Edge.Cuts bottom-left; no negative board coords |
| J2 | **M6 bolt-through bobbins** (6.5 mm drill / 16 mm Cu / 25 mm pitch / via stitch) — previous 2.54 mm pin-header VBAT↔GND short is gone by construction |
| J1 | **Vertical** SuperSeal 26 (`6473418-1`), rotated 90° as EMI wall |
| EMI split | mega-mcu144 **west** of J1; power / PROFET / M6 **east** |
| M1000 | Keepout aligned to silk/pads (official 0.7 polygon); Value **`Module:mega-mcu144/0.7`** |
| Zones | **GND B.Cu** full-board + **VBAT F.Cu** entry/HP/ADIO islands (GND F only around M6−) + module pour keepout |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Footprints | **53** (non-empty board) |

See [HARDWARE_BOM.md](HARDWARE_BOM.md) for kILIS / AmpsPerVolt TODOs.

## Floorplan (mm)

KiCad origin = Edge.Cuts top-left; Y down. AUX = bottom-left `(0, 93)`.

| Block | Placement |
|-------|-----------|
| M1000 | West `(2, 66)` — 42.2 × 40 mm module, keepout on pads |
| J1 EMI wall | `(50, 46.5)` **rot 90°** — vertical SuperSeal between MCU and power |
| J2 VBAT+ M6 | North power-field edge `(92, 11)` — 16 mm Cu, **not** on the MCU west side |
| J3 GND M6 | South power-field edge `(92, 82)` — opposite J2; 71 mm N–S span |
| Power entry | F1 ATO placeholder `(58, 18)` + C1/C2 in the north pocket on the VBAT path; D1 `(80, 28)` |
| HP ×4 | East alley 2×2 @ `(80/96, 40/53)` rot 270° (tabs face north / VBAT) |
| ADIO ×8 | South of SuperSeal 2×4 @ `(52…76, 69.5/77.5)`, west of J3, **between** the bobbins in Y |

```
x=0                    x=45                 x=74                 x=104
+----------------------+--------------------+--------------------+
| mega-mcu144 (M1000)  | vertical SuperSeal | J2 VBAT+ M6 (north)|
| quiet / logic        | 26  EMI SPLIT      | HP PROFET          |
|                      |                    | ADIO  (between)    |
|                      |                    | J3 GND M6 (south)  |
+----------------------+--------------------+--------------------+
                              y=93
```

Bobbins are **not** paired on the east edge and **not** on the M1000 west side.

## Copper strategy (split-bobbin EMI split)

Prefer **zone fills for power/GND**; signal long-haul uses exclusive lanes around the SuperSeal (not through MCU west copper except EN/IS/CAN/SENSOR at the connector spine / north corridor).

1. **VBAT** — F.Cu J2 island `(83.5,1)–(103,22)` (pre-fuse) + post-fuse north `(66.5,1)–(82.5,24)` + HP tabs `(73,32)–(103,64)` + ADIO `(48,66)–(82,81)`; tracks J2→F1.1, F1.2→HP spine x=88; B.Cu matching north islands + east alley stopping at y=61
2. **GND** — B.Cu near-full board (module keepout punches M1000) + F.Cu island around J3 `(82,72)–(103,92)`; stitch vias at M6/HP/SMD
3. **SENSOR_GND** — stays off chassis; **no SENSOR pour**
4. **EN** — exclusive B.Cu MCU–J1 gap columns x=45.15…49.55 + HP pin-south band y≈56.6–63 + ADIO south-of-J1 Y
5. **IS** — local F HP / B-under-ADIO; F.Cu staircase south of ADIO (west of J3) to M1000 S pads
6. **PWR_OUT / ADIO** — stay east of the pin field except J1 landings; F-hop the EN B band

FreeRouting / dense meshes still skipped (mega-mcu144 padstacks).

## Unconnected / routing status

| Metric | Floorplan PR #9 | This copper + fill |
|--------|-----------------|-------------------|
| DRC shorts | not claimed (0 tracks) | **177** (packed east: PWR_OUT3/4, IN_AUX vs PWR_OUT, 10× GND↔VBAT). Old 25 mm M6 GND-vs-VBAT-spine short is **gone** |
| DRC crossings | ~0 (no tracks) | **131** kicad-cli / **387** geometric H–V |
| DRC unconnected | Up (copper stripped) | **87**. VBAT **3** (fuse gap + ADIO island). GND **40** (mostly M1000 keepout). EN/IS union-find **0**; kicad-cli still lists 1-island leftovers on OUT_PWM1–4 / IN_AUX / ADIO |
| EN/IS unconnected | Open | **0** (track-connected) |
| Tracks / vias | 0 / 0 | **406 / 145** |
| Zones filled | 7 unfilled outlines | **9** filled + M1000 keepout |
| Footprints / outline | 54 / 104×93 | 54 / 104×93 |

## DRC notes

`kicad-cli pcb drc` **8.0.9** on the filled board (`scripts/drc_zonefill.json`):

| Issue | Notes |
|-------|-------|
| shorting_items | **177**. Dominant: packed HP/ADIO east (PWR_OUT3↔4, IN_AUX↔PWR_OUT, GND↔VBAT near tabs). Not a 25 mm dual-bobbin pad clash. Human polish. |
| tracks_crossing | **131** kicad-cli / **387** geometric H–V. Human polish in HP/ADIO south. Do **not** replay `cut_crossings_sexp.py`. |
| unconnected_items | **87**. Carrier GND union-find **0** after pour. kicad-cli GND 40 ≈ M1000 keepout + a few SMD via misses. SENSOR_GND ×3 is the dedicated island. |
| solder_mask_bridge | **199**. M6 16 mm pads / module padstack. |
| J1 courtyard | Closed `fp_rect`. **Width 39 mm** (TE). **Length 29 mm** (catalog vertical D). Product-page **36.5 mm** shroud is Cmts.User only. |
| M1000 padstack | Module artifact (`padstack_invalid` 22); ignore for carrier DRC. Keepout outline matches silk `(0.1,0)…(42.2,−40)`. |
| M6 pads | 16 mm Cu on opposite edges — old “GND pad vs VBAT spine” short from the 25 mm pair is gone by construction |

## Schematic sheets

| Sheet | File | Contents |
|-------|------|----------|
| Root | `pdmrazora.kicad_sch` | SuperSeal 26 **vertical** + **split M6 bobbins** (J2 VBAT+ / J3 GND) + power entry + IGN_SW divider |
| MM144 | `MM144.kicad_sch` | mega-mcu144 0.7 + PINMAP globals |
| HP | `HP.kicad_sch` | HP1–4 BTS50010-1TAD + IS sense |
| ADIO | `ADIO.kicad_sch` | ADIO1–8 BTS7004-1EPP + IS/PU |

## Fab-blocker checklist

| # | Blocker | Status |
|---|---------|--------|
| 1 | Real AMP SuperSeal 26 footprint | **Done** (vertical 6473418-1; same pin numbers as CONNECTOR.md) |
| 2 | Final PROFET PNs + sense networks | **Done** |
| 3 | Power entry + IGN_SW divider | **Done** |
| 4 | Place HP/ADIO footprints on PCB | **Done** (re-nested between split M6 bobbins on 104×93) |
| 5 | create-board / copper finish | **Partial** — shorts and crossings are 0; unconnected 75, courtyards 20, M1000 padstack 22. Not fab-clean. No gerbers. |

## Remaining polish (human)

- Not fab-clean. Shorts and crossings are 0. What remains is the leftover table at the top: SENSOR_5V, ADIO SuperSeal landings, IS pins U12–U18 pin 4, split ADIO/HP VBAT pour islands, GND stitch stubs, courtyards, M1000 padstack.
- Do **not** replay `scripts/cut_crossings_sexp.py` (150×130) and do **not** bridge F1.1 to F1.2.
- SENSOR_GND stays off chassis GND (no SENSOR pour).
- TE **6473418-1**: courtyard is 39×29 mm (fits the EMI wall). Product-page 39×36.5 mm shroud **does not fit** without nudging HP/M1000 — verify against the TE drawing before fab
- M6 hardware: two independent copper bobbins + M6×8 button-head, 4 N·m, 25 mm² cable (CONNECTOR.md) — north VBAT / south GND
- ADIO/HP packing between the bobbins is still tight — nudge before fab
- F1 remains the ATO blade placeholder (now on the north VBAT path; J2 pour split so the fuse is not poured around)
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable (`OUT_IO9–13`, `IO1–3`)
- ADIO V-sense divider values (`IN_TPS` / `IN_PPS` / …)

## Scripts

- `scripts/drc_polish_east.py` — **this commit**: placement nudges, fuse-safe VBAT straps, grid re-route, kicad-cli 8 DRC. Do not point it at a 150×130 board.
- `scripts/route_split_bobbins.py` — sexp critical-net router for the J2-north / J3-south nest (rotation used there does not match KiCad; do not re-run on this copper)
- `scripts/fill_zones_split.py` — **this commit**: pcbnew 8 ZONE_FILLER, solid VBAT/GND pours, M6/HP via stitch, kicad-cli DRC
- `scripts/drc_zonefill.json` — compact DRC counts from kicad-cli 8.0.9
- `scripts/unconnected_leftover.txt` — pad-island leftover list
- `scripts/copper_fill_overview.png` — F/B pour overview
- `scripts/split_bobbins_floorplan.py` — PR #9 placement (do not re-run blindly; wipes copper)
- `scripts/layout_positions.txt` — current footprint XY
- `scripts/floorplan_fcu_overview.png` — F.Cu pad/outline overview of the nest
- `scripts/fill_zones_104x93.py` / `scripts/route_critical_nets.py` — paired-M6 104×93 copper; do not re-run on this nest
- `scripts/layout_redesign.py` — original 104×93 shrink + dual-bobbin J2
- Older copper scripts (`cut_crossings_sexp.py`, `route_is_longhaul_thin_en.py`, …) target the **old** 150×130 nest and must not be re-applied blindly
