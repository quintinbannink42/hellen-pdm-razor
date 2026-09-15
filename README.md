# hellen-pdm-razor

Hellen-One **frame** hardware for a Link ECU **Razor PDM**-compatible power distribution module.

| | |
|---|---|
| **Connector** | 26-pin AMP SuperSeal 1.0 (Link “Connector C”) — pinout in [CONNECTOR.md](CONNECTOR.md) |
| **Main power** | M6 + / − (VBAT / GND), not on the SuperSeal |
| **MCU module** | [mega-mcu144](https://github.com/andreika-git/hellen-one/tree/master/modules/mega-mcu144) **rev ≥ 0.7** (STM32F767) |
| **I/O target** | 4× high-power (25 A / 80 A peak class) + 8× ADIO (8 A) |
| **Default branch** | `main` (required by hellen-one automation) |

> **This is NOT [HELLCORE](https://github.com/quintinbannink42/HELLCORE).** HELLCORE is a separate project. This repo is a Hellen-One PDM carrier matching the Razor loom connector only.

## Docs

| File | Contents |
|------|----------|
| [CONNECTOR.md](CONNECTOR.md) | Exact Razor 26-pin + M6 pinout (authoritative) |
| [PINMAP.md](PINMAP.md) | mega-mcu144 edge → HP / ADIO / system nets |
| [REV1_SPEC.md](REV1_SPEC.md) | Goals, architecture, e-fuse behaviour |
| [BLOCK_DIAGRAM.md](BLOCK_DIAGRAM.md) | Carrier block diagram |
| [BOARD.md](BOARD.md) | What’s stubbed vs next; module placement steps |

## KiCad project

- `pdmrazora.kicad_pro` / `.kicad_sch` / `.kicad_pcb` (no dashes/underscores — hellen-one requirement)
- `revision.txt` → `BOARD_PREFIX=pdm` `BOARD_SUFFIX=razor` `BOARD_REVISION=a`

Schematic includes the SuperSeal with **exact Razor nets**, M6 VBAT+/GND stubs, USB-C note, and TODO blocks for HP PROFET ×4 and ADIO ×8. Full mega-mcu144 module merge lands after submodule init + hellen-one create-board flow (see BOARD.md).

## How to build (Hellen-One)

1. `git clone --recurse-submodules https://github.com/quintinbannink42/hellen-pdm-razor.git`
2. Open `pdmrazora.kicad_pro` in KiCad 6+ (8/9 OK for editing the frame).
3. Place / refresh the **mega-mcu144 ≥ 0.7** module footprint from the `hellen-one` submodule (see [hellen-one wiki](https://github.com/andreika-git/hellen-one/wiki)).
4. Route connector nets per CONNECTOR.md / PINMAP.md; fill HP PROFET and ADIO stages.
5. Push to **`main`**. GitHub Action `.github/workflows/create-board.yaml` calls hellen-one create-board to merge module gerbers into `boards/`.
6. Daily workflows keep `hellen-one` and `kicad6-libraries` submodule refs updated.

Frame rules (from hellen-example FAQ):

- No `-` or `_` in KiCad filenames
- `aux_axis_origin` required; board origin at **bottom-left** (no negative coordinates)

## Firmware intent

Firmware is **not** this repo. Planned RusEFI custom board overlay (electronic fuse + channel map), e.g. based on [fw-custom-hellen144-f4](https://github.com/rusefi/fw-custom-hellen144-f4) / `hellen-common-mega144.mk`, with `protected_gpio` for HP1–4 + ADIO1–4 first. See PINMAP.md and REV1_SPEC.md.

## Submodules

```
hellen-one          https://github.com/andreika-git/hellen-one
kicad6-libraries    https://github.com/rusefi/kicad6-libraries
```

Skeleton mirrors [rusefi/hellen-example](https://github.com/rusefi/hellen-example).
