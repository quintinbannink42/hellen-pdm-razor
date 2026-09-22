# Board status — PowerCore (`pdmrazora` rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — ADIO column spread (IS alley in X)

Packing pass on the carrier-close tip. Does not move J1, M1000, J2, J3, F1, U3, or U4. Board stays 104×93. J2 north / J3 south. No SENSOR_GND pour. F1 is not bridged. `scripts/cut_crossings_sexp.py` and the 150×130 routers were not replayed. No gerbers.

[F.Cu / B.Cu overview](scripts/copper_fill_overview.png)

`kicad-cli pcb drc` **8.0.9**, `--severity-error`, `--units mm`.

| Issue | Carrier close | After this pack |
|-------|-------------:|----------------:|
| shorting_items | 0 | **0** |
| tracks_crossing | 0 | **0** |
| clearance | 0 | **0** |
| unconnected_items | 60 | **60** |
| courtyards_overlap | 20 | **20** |
| padstack_invalid | 22 | **22** (M1000, left alone) |
| Tracks / vias | 1205 / 231 | **1219 / 231** |

SENSOR_GND pours: **0**. Fuse still open. The spread does not change the ratsnest count. It widens the copper gap between ADIO packages from 0.990 mm to 1.340 mm so a 0.60 mm via fits in X. The south run is still walled in Y. Stopped there instead of searching another 0.20 mm grid.

### Footprint moves

Column pitch grows by **0.35 mm per gap**. Column 0 (U11, U15, and its R/C) stays. Y and rotation are unchanged. 0.50 mm per gap would push C104's courtyard (right edge 80.325 + 1.50 = 81.825) through J3's courtyard (left 81.455). At 0.35 mm, C104's courtyard right is 81.375, 0.08 mm clear of J3.

| Refs | Before x | After x | dx |
|------|----------|---------|----|
| U12, U16, R202, R206 | 60.000 | 60.350 | +0.35 |
| R102, R106 | 57.200 | 57.550 | +0.35 |
| C102, C106 | 62.800 | 63.150 | +0.35 |
| U13, U17, R203, R207 | 68.000 | 68.700 | +0.70 |
| R103, R107 | 65.200 | 65.900 | +0.70 |
| C103, C107 | 70.800 | 71.500 | +0.70 |
| U14, U18, R204, R208 | 76.000 | 77.050 | +1.05 |
| R104, R108 | 73.200 | 74.250 | +1.05 |
| C104, C108 | 78.800 | 79.850 | +1.05 |

Copper that already lived inside a column moves with that column. Seven vertical fanouts that cross y=67.05 are split, with the jog at y=66.52 or y=66.98 (above the C30/R30 pads, below the driver pads). The IN_AUX1 spine at x=72.00 jogs to x=72.70 south of that line, into the new U13/U14 gap. The IN_AUX2/IN_AUX4 spines at x=80.00, 80.80, and 81.60 shift **+1.00 mm** (endpoints with y≥63.5) so U14's new east pad edge at x=80.555 stays 0.34 mm off the spine copper.

### Why the IS pins are still open

U12.4 can enter the new gap: `seg_ok` accepts a 0.20 mm track and a via at (56.10, 71.40), (56.10, 74.20), and (56.10, 79.20). South of the via the run meets horizontal buses on a **0.80 mm** pitch:

| Y | Net | Layer |
|---|-----|-------|
| 74.80 | OUT_IO8 | B |
| 75.60 | OUT_IO7 | B |
| 76.40 | OUT_IO6 | B |
| 76.80 / 78.40 | ADIO5 | F |
| 77.20 | IN_AUX3 | B |
| 80.00 | IN_AUX4 and IN_O2S | F and B, same Y |

0.80 mm center pitch with 0.20 mm tracks leaves 0.60 mm between copper edges: one track, no room to change layers. A 0.60/0.30 via needs 1.20 mm between foreign track centers. Shifting one of those buses by the 0.40 mm that would open a via lands it on the next bus. That is the stop.

### Why J1 did not move

SuperSeal column D copper ends at x=43.30. M1000's east pads start at x=43.70. The gap is **0.40 mm**; one 0.20 mm track needs **0.60 mm**. The pin columns are west of that wall, so moving J1 east or M1000 west makes the gap smaller. Moving J1 west is limited by the mounting-hole copper (origin x − 1.65) meeting the OUT_IO5 fanout at x=44.8; about 2.0 mm west opens a 2.40 mm alley (five tracks) and leaves the hole 0.25 mm from that track. Eight ADIO nets in one alley need about 3.4 mm. The south exit is the S-pad row at y=65.70 (0.60 mm pads, 1.20 mm pitch, **0.60 mm** gaps — one track, and the gap is inside the footprint, so sliding J1 does not widen it). SENSOR_5V crosses that alley near y=62. The north pad wall is 0.60 mm pads on a 0.80 mm pitch (**0.20 mm** cracks) from x=2 to x=44.3, closed at the east corner by the GND finger. Those cracks are inside M1000 and do not open when the module is translated. The west-edge channel is about 1.3 mm (two tracks). J1 and M1000 stay put.

VBAT is still 1 fuse gap + 10 zone islands. No strap was added.

## Previous commit — carrier ratsnest close (stacked on the DRC polish)

Does not undo the polish anchors (U3/U4 at +90°, J1 at x=48.8, D1 at (88, 24), sense RC at y=35.70). Board stays 104×93, J2 north / J3 south, M1000 west. No SENSOR_GND pour. F1 is not bridged. `scripts/cut_crossings_sexp.py` was not replayed. No gerbers.

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
