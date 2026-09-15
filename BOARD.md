# Board status — pdmrazora (rev a)

## This commit

| Item | Status |
|------|--------|
| Hellen-example skeleton | Done |
| Connector / pin map / spec docs | Done |
| KiCad frame `pdmrazora.*` | Done — SuperSeal nets match Razor pinout |
| **26-pin SuperSeal footprint** | **Done** — TE **9-6437287-8**, FP `pdmrazora:TE_9-6437287-8_SuperSeal26` |
| M6 VBAT+ / GND stubs | Done |
| USB-C | Enclosure note; nets on MM144 |
| mega-mcu144 **0.7** | **Placed** (`M1000`) |
| HP PROFET ×4 | **BTS50010-1TAD** + RIS 2k7 / 10n; footprints on PCB |
| ADIO ×8 | **BTS7004-1EPP** + RIS 4k7 / PU 4k7; footprints on PCB |
| Power entry + IGN_SW divider | **Done (schematic)** — F1, TVS SMBJ33CA, bulk caps, 100k/10k → IN_VIGN |
| Fab outputs `boards/pdmrazora/` | After create-board Action |

See [HARDWARE_BOM.md](HARDWARE_BOM.md) for kILIS / AmpsPerVolt TODOs.

## Hellen module placement

- Submodules: `hellen-one` + `kicad6-libraries`
- Module: `hellen-one/modules/mega-mcu144/0.7/` → `M1000` at (15, 55) mm, rotation **0°**
- Outline **180 × 140 mm**; `aux_axis_origin` bottom-left `(0, 140)`; no negative coordinates
- Value string for gerber merge: `Module:mega-mcu144/0.7`

## Schematic sheets

| Sheet | File | Contents |
|-------|------|----------|
| Root | `pdmrazora.kicad_sch` | SuperSeal 26 (9-6437287-8) + M6 + power entry + IGN_SW divider |
| MM144 | `MM144.kicad_sch` | mega-mcu144 0.7 + PINMAP globals |
| HP | `HP.kicad_sch` | HP1–4 BTS50010-1TAD + IS sense |
| ADIO | `ADIO.kicad_sch` | ADIO1–8 BTS7004-1EPP + IS/PU |

## Fab-blocker checklist

| # | Blocker | Status |
|---|---------|--------|
| 1 | Real AMP SuperSeal 26 footprint | **Done** — TE 9-6437287-8 / project pretty |
| 2 | Final PROFET PNs + sense networks | **Done** — BTS50010-1TAD + BTS7004-1EPP; RIS/PU/docs |
| 3 | Power entry + IGN_SW divider | **Done (schematic)** — PCB pads for F1/TVS/caps still partial (ratnest) |
| 4 | Place HP/ADIO footprints on PCB | **Done** — nets assigned; thermal zones stubbed; full length routing **partial** |
| 5 | create-board / copper finish | **Partial** — push triggers workflow; finish routing + ideal-diode part later |

## Remaining (non-blocking polish)

- Ideal-diode / reverse-protect controller PN + footprint
- Discrete FET for ADIO PU hard-enable (soft R to SENSOR_5V placed)
- Full length-perfect routing SuperSeal ↔ PROFET ↔ module
- ADIO V-sense divider resistor values
- ERC/DRC cleanup after KiCad reload

## PCB notes (rev a)

- Outline **180 × 140 mm**; origin bottom-left; `aux_axis_origin 0 140`
- J1 = production SuperSeal FP (not pin-header)
- HP U1–U4 TO-263-7 on right; ADIO U11–U18 TSDSO-14 mid-right; thermal Cu zones on VBAT/OUT
