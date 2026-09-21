# Board status — PowerCore (`pdmrazora` rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — EMI-split floorplan, M6 bobbins, vertical SuperSeal, M1000 0.7 keepout fix

| Item | Status |
|------|--------|
| Board outline | **150 × 130 → 124 × 106 mm** (Razor-class ~103.6 × 93.4; Edge.Cuts fits nested parts + M6 14 mm pads) |
| J1 | **Vertical** TE **6437288-6** (straight, keying 1) — MCU west / PROFET east EMI split. Razor 26-pin net pinout unchanged. |
| J2 | **Dual M6 bolt-through bobbins** 22 mm pitch (6.5 mm drill / 14 mm pad) replacing 2.54 mm pin-header stubs |
| M1000 | Refreshed from `hellen-one/modules/mega-mcu144/0.7`; keepout polygon = silk (0.1,−40)…(42.2,−0.1); Value **`Module:mega-mcu144/0.7`**; rot 0°; origin bottom-left |
| Geom EN/IS unconnected | **0** (all 12 EN + all 12 IS long-haul still closed) |
| Geom unconnected (tracks) | **15** (was DRC 116) — remaining mostly GND pour islands until zone fill |
| Geom track crossings | **~1107** (was DRC 89) — expected after full re-nest; EN=B.Cu / IS=F.Cu exclusive south corridor + spine at x≈88.8. Needs Pcbnew DRC + interactive cleanup. |
| J2 VBAT↔GND stub short | **Gone** (22 mm M6 pitch vs old 2.54 mm header with 3 mm pads) |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Branding | **PowerCore** — user-facing docs; KiCad stem stays `pdmrazora` |

`kicad-cli pcb drc` was **not available** in this environment. Numbers above are a track-segment geometry proxy (`scripts/redesign_floorplan.py`). Re-run DRC in KiCad 8/9 after zone fill; do not treat geom crossings as the fab DRC sheet.

See [HARDWARE_BOM.md](HARDWARE_BOM.md) for M6 / SuperSeal PN assumptions and kILIS / AmpsPerVolt TODOs.

## Floorplan (mm)

EMI split: **mega-mcu144 west of the vertical SuperSeal, HP/ADIO/M6 east**.

| Block | Placement |
|-------|-----------|
| M1000 | West `(6.5, 48)` rot **0°** — keepout/silk/pads aligned to module 42.2 × 40 mm |
| J1 vertical | Mid `(58.5, 46)` rot **90°** — housing ~51–88 × 28–67; mating face up |
| ADIO ×8 | East 2×4 @ x=93/105, y=11…44 |
| HP ×4 | East-south TO-263 @ `(95/109, 66/80)` rot 270° |
| J2 M6 pair | Power-side south `(90, 94)` — pad1 VBAT+ @90, pad2 GND @112 |
| Power entry | F1/D1/C1/C2/R1/R2 on the PROFET side of J1 |

## Copper strategy

Prefer **zone fills for power/GND** + **selective Manhattan tracks** (not a dense star mesh):

1. **VBAT** — F.Cu pour on the power side (x≥88) + spine to M6 pad 1 / fuse / PROFET VS
2. **GND** — B.Cu near-full board (keepout punches module) + M6 pad 2 stitch
3. **PWR_OUT1..4** — local OUT islands + F.Cu to paired SuperSeal pins
4. **ADIO1..8** — local OUT + F.Cu to SuperSeal
5. **EN** — exclusive **B.Cu** south corridor (y≈51–57) + spine x≈88.8
6. **IS** — exclusive **F.Cu** same Y corridor (opposite layer from EN)

FreeRouting / aggressive track meshes were skipped (mega-mcu144 padstacks + prior short storms).

## Unconnected / routing status

| Metric | Previous (150×130, RA J1, pin-header J2) | This commit |
|--------|------------------------------------------|-------------|
| DRC shorts | **1** (J2 stub) | **0 expected** for that stub (M6) — confirm in Pcbnew |
| DRC crossings | **89** | geom proxy **~1107** (re-nest; not a KiCad DRC run) |
| DRC unconnected | **116** | geom proxy **15** |
| EN/IS unconnected | **0** | **0** |
| Board outline | 150 × 130 | **124 × 106** |
| J1 orientation | RA 9-6437287-8, bottom edge | **Vertical 6437288-6**, mid-board split |
| J2 | 2.54 mm pin-header | **M6 bobbins 22 mm** |

### Remaining ratsnest / multi-pad gaps

- **GND** pour islands until zone fill in Pcbnew
- A few **VBAT** zone-to-zone / pad edges
- IS/EN exclusive lanes are closed but still share a packed south corridor (same-Y via packing / F-hops still TODO)

## DRC notes

Geometry proxy after this commit (no `kicad-cli` in the agent VM):

| Issue | Notes |
|-------|-------|
| shorting_items | Old J2 2.54 mm VBAT↔GND short **removed**. M6 pads 22 mm C-C, 14 mm copper (8 mm gap). |
| tracks_crossing | Geom ~1107 after re-nest. EN/IS on opposite layers. Interactive: hop remaining same-layer H without reopening EN/IS. |
| solder_mask_bridge | Module / via density — non-blocking for this stage |
| J1 courtyard | Vertical FP uses a **closed** `F.CrtYd` rectangle (old RA courtyard was open) |
| M1000 padstack | Module artifact; ignore for carrier DRC |

## Schematic sheets

| Sheet | File | Contents |
|-------|------|----------|
| Root | `pdmrazora.kicad_sch` | SuperSeal 26 **vertical** + **M6 bobbins** + power entry + IGN_SW divider |
| MM144 | `MM144.kicad_sch` | mega-mcu144 0.7 + PINMAP globals |
| HP | `HP.kicad_sch` | HP1–4 BTS50010-1TAD + IS sense |
| ADIO | `ADIO.kicad_sch` | ADIO1–8 BTS7004-1EPP + IS/PU |

## Fab-blocker checklist

| # | Blocker | Status |
|---|---------|--------|
| 1 | Real AMP SuperSeal 26 footprint | **Done** (now vertical 6437288-6; same pin pattern) |
| 2 | Final PROFET PNs + sense networks | **Done** |
| 3 | Power entry + IGN_SW divider | **Done** |
| 4 | Place HP/ADIO footprints on PCB | **Done** (re-nested) |
| 5 | M6 bolt-through mechanicals | **Done** (PN assumptions in HARDWARE_BOM.md) |
| 6 | create-board / copper finish | **Partial** — EN/IS closed after re-nest; crossings need Pcbnew DRC + fill |

## Remaining polish

- Fill zones in Pcbnew and run `kicad-cli pcb drc`; hop remaining same-layer crossings without new shorts
- Finish remaining PWR/ADIO/CAN stub gaps without recreating shorts
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable
- ADIO V-sense divider values

## Scripts

- `scripts/redesign_floorplan.py` — nest EMI-split floorplan, M6/J1/M1000 rebuild, EN/IS exclusive-lane route (this commit)
- `scripts/layout_positions.txt` — current footprint origins
- `scripts/redesign_status.txt` — before/after size + geom DRC proxy
- `scripts/surgical_drc_fix.py` — delete shorting/crossing copper by DRC UUID; SENSOR taps + GND stitches
- `scripts/drc_cleanup_route.py` — full selective re-route attempt (reference; denser rebuild)
- `scripts/restore_connectivity.py` — family restore helpers
- `scripts/route_en_is_lanes.py` — gated EN/IS exclusive-lane re-route (prior commit)
- `scripts/route_is_longhaul_thin_en.py` — remaining 9 IS B south-ring + EN B thin
- `scripts/yank_adio_pwr_south.py` — ADIO U-turn Y-shift + orphan PWR south-delete
- `scripts/cut_crossings_sexp.py` — gated S-expr AUX1 J1-gap + EN/ADIO F-hops (prior)
- `scripts/copper_status.txt` — prior commit metrics
- `scripts/fill_and_route.py` — original pour fill + selective copper (prior commit)
