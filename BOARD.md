# Board status — pdmrazora (rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — copper fill + selective routing

| Item | Status |
|------|--------|
| Nested floorplan | **Done** — 53 footprints on **150 × 130 mm** |
| Zone fills | **Done** — VBAT / GND / PWR_OUT1–4 / ADIO1–8 filled; M1000 keepout respected (no pour under module) |
| Tracks / vias | **328 tracks + 82 vias** (was 0) |
| Unconnected (DRC) | **254 → 97** |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |

See [HARDWARE_BOM.md](HARDWARE_BOM.md) for kILIS / AmpsPerVolt TODOs.

## Floorplan (mm)

| Block | Placement |
|-------|-----------|
| M1000 | Left `(8,52)` — clear Hellen merge keepout |
| ADIO ×8 | Mid-top 2×4 @ y≈16/42, x=70…124 |
| HP ×4 | Lower-right TO-263 @ `(92/115, 68/90)` rot 270° |
| J1 | Bottom edge center |
| Power entry | Left-bottom J2 → F1 → C1/C2/D1; IGN divider above |

## Copper strategy

Prefer **zone fills for power/GND** + **selective Manhattan tracks** (not a dense star mesh):

1. **VBAT** — F.Cu pours: power-entry island, HP island, bottom link, ADIO supply strips; stubs from ADIO thermal pads + M1000.N27
2. **GND** — B.Cu near-full board (keepout punches module) + F.Cu entry/HP islands
3. **PWR_OUT1..4** — local islands at HP OUT + wide F.Cu corridors to dual SuperSeal pins (unique mid-x / target-y)
4. **ADIO1..8** — local OUT islands + B.Cu long corridors (left bank x≈62–67, right bank x≈132–136) to J1
5. **Control/sense** — EN/PWM/IO and ISENSE via adjacent vias + exclusive B.Cu lanes into M1000 east/south pads
6. **System** — IGN_SW→divider→IN_VIGN; CANH/CANL left-edge B.Cu; SENSOR_5V/GND bottom B.Cu spines to J1 + M1000

FreeRouting / aggressive track meshes were skipped (mega-mcu144 padstacks + prior short storms).

## Unconnected / routing status

| Metric | Nest commit (a39b6c3) | This commit |
|--------|----------------------|-------------|
| DRC unconnected | **254** | **97** |
| Tracks | 0 | **328** |
| Vias | 0 | **82** |
| Zones with fill | 0 (outlines only) | **20/20** copper zones filled |
| Footprints | 53 | 53 |
| Board outline | 150 × 130 | 150 × 130 |

### Remaining ratsnest / multi-pad gaps

- Some **GND** pad islands outside F.Cu pours still need vias/stitches (B.Cu pour present)
- **SENSOR_5V** to ADIO PU resistors (R201–R208) — J1↔M1000 spine done; local PU taps still open
- A few **VBAT** / sense pad edges outside pour connectivity tolerance
- EN/IS routes present but may need interactive cleanup where DRC reports crossings

## DRC notes

`kicad-cli pcb drc` after this commit (~315 error-level findings):

| Issue | Notes |
|-------|-------|
| shorting_items / tracks_crossing (~90–110) | Manhattan B/F lane congestion near HP/ADIO/M1000; **interactive cleanup** next — do not treat as fab-ready |
| solder_mask_bridge | J2 stub / module / via density — non-blocking for this stage |
| J2 VBAT↔GND clearance | Pin-header stub pads at 2.54 mm; replace with real M6 later |
| J1 malformed courtyard | Pre-existing SuperSeal FP courtyard not closed |
| M1000 padstack | Module artifact; ignore for carrier DRC |
| clearance / hole_clearance | Mostly via-to-track near dense clusters |

## Schematic sheets

| Sheet | File | Contents |
|-------|------|----------|
| Root | `pdmrazora.kicad_sch` | SuperSeal 26 + M6 + power entry + IGN_SW divider |
| MM144 | `MM144.kicad_sch` | mega-mcu144 0.7 + PINMAP globals |
| HP | `HP.kicad_sch` | HP1–4 BTS50010-1TAD + IS sense |
| ADIO | `ADIO.kicad_sch` | ADIO1–8 BTS7004-1EPP + IS/PU |

## Fab-blocker checklist

| # | Blocker | Status |
|---|---------|--------|
| 1 | Real AMP SuperSeal 26 footprint | **Done** |
| 2 | Final PROFET PNs + sense networks | **Done** |
| 3 | Power entry + IGN_SW divider | **Done** |
| 4 | Place HP/ADIO footprints on PCB | **Done** |
| 5 | create-board / copper finish | **Partial** — pours filled + substantial routing; DRC shorts/crossings need interactive cleanup |

## Remaining polish

- Interactive DRC cleanup of shorts/crossings (priority: PWR_OUT↔ADIO, EN↔IS near drivers)
- SENSOR_5V taps to R201–R208
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable
- Replace J2 pin-header with true M6 mechanical
- ADIO V-sense divider values

## Scripts

- `scripts/fill_and_route.py` — reshape/fill zones + selective copper; downgrades K9 save → K8 headers
- `scripts/copper_status.txt` — before/after metrics
