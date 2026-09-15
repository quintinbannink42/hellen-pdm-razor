# Board status — pdmrazora (rev a)

## This commit

| Item | Status |
|------|--------|
| Hellen-example skeleton (`.gitmodules`, workflows, `revision.txt`, `.gitignore`) | Done |
| Authoritative connector / pin map / spec docs | Done (`CONNECTOR.md`, `PINMAP.md`, …) |
| KiCad frame `pdmrazora.*` | Done — SuperSeal nets match Razor pinout |
| 26-pin SuperSeal symbol + net labels | Done (generic `Conn_02x13_Top_Bottom` placeholder footprint) |
| M6 VBAT+ / GND stubs | Done (schematic + PCB pad placeholders) |
| USB-C | Enclosure note; nets `USBM` / `USBP` / `USBID` on MM144 sheet |
| mega-mcu144 **0.7** module | **Placed** — footprint `M1000` on PCB (`Module:mega-mcu144/0.7`), symbol + PINMAP edge labels on sheet `MM144.kicad_sch` |
| HP PROFET ×4 | **Schematic stubs** — sheet `HP.kicad_sch`, Infineon `BTS50010-1TAD` as 40 A-class stand-in (`BTS50010-1TAD-TBD`); exact PN TBD |
| ADIO ×8 | **Schematic stubs** — sheet `ADIO.kicad_sch`, generic `BTS70xx-TBD` 8 A high-side + V/I/PU labels per PINMAP |
| Fab outputs under `boards/pdmrazora/` | After create-board Action succeeds |

## Hellen module placement

Follow the [hellen-one wiki](https://github.com/andreika-git/hellen-one/wiki) “frame” workflow.

- Submodules: `hellen-one` + `kicad6-libraries`
- Module files: `hellen-one/modules/mega-mcu144/0.7/`
- Footprint lib: `fp-lib-table` → `hellen-one-mega-mcu144-0.7`
- Symbol lib: `sym-lib-table` → `mega-mcu144-0.7`
- PCB: `M1000` at (15, 55) mm, rotation **0°** (90° multiple). Outline enlarged to **160 × 120 mm**. `aux_axis_origin` bottom-left `(0, 120)`. No negative board coordinates.
- Value string for gerber merge: `Module:mega-mcu144/0.7`

Edge nets already labeled toward Razor (global labels, PINMAP.md):

- CANH / CANL → SuperSeal
- OUT_PWR_EN, USB (USBM/USBP/USBID)
- HP EN/PWM (`OUT_PWM1..4`) and IS (`IN_AUX1..4`)
- ADIO EN / I-sense / V-sense / PU (`OUT_PWM5..8`, `OUT_IO5..8`, `IN_MAP*`, `IN_O2S*`, `IN_RES*`, `IN_TPS*`, `OUT_IO9..13`, `IO1..3`)
- SENSOR_5V ← `V5A_SWITCHABLE`; SENSOR_GND ← `GNDA` (do **not** bond to chassis)
- IGN_SW still needs a divider into `IN_VIGN` (not yet a discrete stage)

## Schematic sheets

| Sheet | File | Contents |
|-------|------|----------|
| Root | `pdmrazora.kicad_sch` | SuperSeal 26 + M6 power |
| MM144 | `MM144.kicad_sch` | mega-mcu144 0.7 + PINMAP globals |
| HP | `HP.kicad_sch` | HP1–4 PROFET stubs |
| ADIO | `ADIO.kicad_sch` | ADIO1–8 8 A HS + sense/PU stubs |

## Remaining fab blockers

1. **Replace SuperSeal footprint** — current `PinHeader_2x13` is not a production AMP SuperSeal 26 FP.
2. **Pick exact HP PROFET PN** — `BTS50010-1TAD` is a 40 A / 1 mΩ class placeholder. Confirm continuous 25 A / 80 A peak SOA, package, and IS scaling; likely BTS7xxx / BTS50xxx family. Update Value + footprint before fab.
3. **Pick exact ADIO PN** — `BTS70xx-TBD` generic 8 A high-side. Add sense resistors / dividers for I-sense and V-sense; PU FET or resistor for `OUT_IOx` enable.
4. **Power entry** — TVS, reverse protection, input fuse; IGN_SW divider → `IN_VIGN`.
5. **Copper** — route SuperSeal / M6 / module edge pads; HP/ADIO footprints not on PCB yet (schematic-only stubs).
6. **create-board** — push to `main` so `.github/workflows/create-board.yaml` can merge module gerbers into `boards/`.

Useful references:

- https://github.com/andreika-git/hellen-one/wiki
- https://wiki.rusefi.com/Hellen-One-Platform
- Example frames: [rusefi/uaefi](https://github.com/rusefi/uaefi), [rusefi/hellen-example](https://github.com/rusefi/hellen-example), [rusefi/alphax-2chan](https://github.com/rusefi/alphax-2chan)

## PCB notes (rev a)

- Outline **160 × 120 mm**; origin bottom-left; `aux_axis_origin 0 120`.
- Connector footprint is a **placeholder** — replace with a verified AMP SuperSeal 26 footprint before fab.
- mega-mcu144 **0.7** footprint is placed (`M1000`). Eco1 keepout placeholder removed.
