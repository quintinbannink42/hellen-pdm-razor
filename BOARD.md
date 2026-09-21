# Board status — PowerCore (`pdmrazora` rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — mechanical / floorplan redesign (Quintin)

| Item | Status |
|------|--------|
| Outline | **150 × 130 → 104 × 93 mm** (Link Razor class: enclosure 103.6 × 93.4) |
| AUX origin | **(0, 93)** — Edge.Cuts bottom-left; no negative board coords |
| J2 | **M6 bolt-through bobbins** (6.5 mm drill / 16 mm Cu / 25 mm pitch / via stitch) — previous 2.54 mm pin-header VBAT↔GND short is gone by construction |
| J1 | **Vertical** SuperSeal 26 (`6473418-1`), rotated 90° as EMI wall |
| EMI split | mega-mcu144 **west** of J1; power / PROFET / M6 **east** |
| M1000 | Keepout aligned to silk/pads (official 0.7 polygon); Value **`Module:mega-mcu144/0.7`** |
| Tracks / vias | **0 / 0** (old Manhattan copper deleted — coordinates were invalid after the move) |
| Zones | Coarse **GND B.Cu** full-board + **VBAT/GND F.Cu** power-side islands + module pour keepout |
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
| M6 bobbins | East-north J2 `(91, 14)` — pad1 VBAT+ @ y=14, pad2 GND @ y=39 |
| Power entry | F1 / D1 / C1 / C2 / IGN divider just west of the bobbins |
| HP ×4 | East TO-263 2×2 @ `(80/96, 58/71)` rot 270° |
| ADIO ×8 | South-east 2×4 @ y≈82/89, x=70…97 |

```
x=0                    x=45                 x=68                 x=104
+----------------------+--------------------+--------------------+
| mega-mcu144 (M1000)  | vertical SuperSeal | M6+ / M6− bobbins  |
| quiet / logic        | 26  EMI SPLIT      | HP PROFET + ADIO   |
+----------------------+--------------------+--------------------+
                              y=93
```

## Copper strategy (after the move)

Prefer **zone fills for power/GND**; all previous EN/IS long-haul tracks were tied to the 150×130 nest and are **not** valid on this outline.

1. **VBAT** — F.Cu pour on the power half (x≳67); M6+ pad is 16 mm with stitch vias
2. **GND** — B.Cu near-full board (module keepout punches M1000) + F.Cu power-half island; M6− pad matching
3. **PWR_OUT / ADIO / control** — **unrouted** (human copper polish)

FreeRouting / dense meshes still skipped (mega-mcu144 padstacks).

## Unconnected / routing status

| Metric | Previous (150×130 nest) | This commit |
|--------|-------------------------|-------------|
| DRC shorts | **1** (J2 2.54 mm header) | **Not run in this environment** (no `kicad-cli`). J2 header short **removed** (25 mm M6 pitch) |
| DRC crossings | **89** | **Expected ~0** (no tracks left to cross) |
| DRC unconnected | **116** | **Up** — EN/IS/ADIO/PWR long-haul must be re-done on the new floorplan |
| EN/IS unconnected | **0** | **Open again** (copper stripped with the move) |
| Tracks | 346 | **0** |
| Vias | 142 | **0** (M6 stitch vias live in the J2 footprint) |
| Footprints | 53 | **53** |
| Board outline | 150 × 130 | **104 × 93** |

## DRC notes

`kicad-cli pcb drc` was **not available** in the agent VM (no KiCad package). Mechanical intent:

| Issue | Notes |
|-------|-------|
| shorting_items | Previous unique short was J2 pin-header VBAT↔GND @ 2.54 mm. M6 pads are 25 mm apart with 16 mm Cu — will not short each other. Remaining shorts = zone-to-pad after a fill, for a human to check. |
| tracks_crossing | No board tracks; crossings should collapse until new routing. |
| solder_mask_bridge | M6 16 mm pads / module padstack — inspect after pour. |
| J1 courtyard | Closed `fp_rect` (previous RA courtyard was open). TE body is 39 × 36.5 mm; courtyard is pin-field + mounting (~37 × 23.5 mm). **Verify against 6473418-1 drawing** — shroud may need a larger keepout. |
| M1000 padstack | Module artifact; ignore for carrier DRC. Keepout now matches silk `(0.1,0)…(42.2,−40)`. |

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
| 1 | Real AMP SuperSeal 26 footprint | **Done** (vertical 6473418-1; same pin numbers as CONNECTOR.md) |
| 2 | Final PROFET PNs + sense networks | **Done** |
| 3 | Power entry + IGN_SW divider | **Done** |
| 4 | Place HP/ADIO footprints on PCB | **Done** (re-nested on 104×93) |
| 5 | create-board / copper finish | **Open** — floorplan only; EN/IS/ADIO/PWR copper is human polish |

## Remaining polish (human)

- Re-route EN / IS / ADIO / PWR_OUT / CAN / SENSOR after the EMI split (do not blindly restore the 150×130 south-ring)
- Pour/refill VBAT & GND; stitch around M6 bobbins and HP tabs; confirm no zone-to-zone shorts at the SuperSeal wall
- Confirm TE **6473418-1** (or 6437288-6 if no mounting holes) 3D/courtyard vs the 39×36.5 mm datasheet body
- M6 hardware: copper bobbin + M6×8 button-head, 4 N·m, 25 mm² cable (CONNECTOR.md)
- ADIO/HP courtyard packing on the east half is tight (~104 mm) — nudge before fab
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable
- ADIO V-sense divider values

## Scripts

- `scripts/layout_redesign.py` — **this commit**: 104×93 Edge.Cuts, M6 bobbins, vertical SuperSeal EMI wall, M1000 keepout/value
- `scripts/layout_positions.txt` — current footprint XY
- Older copper scripts (`cut_crossings_sexp.py`, `route_is_longhaul_thin_en.py`, …) target the **old** 150×130 nest and must not be re-applied blindly
