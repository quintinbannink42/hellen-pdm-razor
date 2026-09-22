# PowerCore

Hellen-One **hardware** for **PowerCore**, a standalone automotive power distribution module (PDM) with a **Link Razor PDM**-compatible SuperSeal loom.

| | |
|---|---|
| **Product** | **PowerCore** (not an engine ECU) |
| **Connector** | 26-pin AMP SuperSeal 1.0 (Link “Connector C”) — pinout in [CONNECTOR.md](CONNECTOR.md) |
| **Main power** | M6 + / − (VBAT / GND), not on the SuperSeal |
| **MCU module** | [mega-mcu144](https://github.com/andreika-git/hellen-one/tree/master/modules/mega-mcu144) **rev ≥ 0.7** (STM32F767) |
| **I/O target** | 4× high-power (25 A / 80 A peak class) + 8× ADIO (8 A) |
| **KiCad stem** | `pdmrazora` (hellen-one: no dashes/underscores — **do not rename**) |
| **GitHub path** | `hellen-pdm-razor` (legacy repo name; product name is PowerCore) |
| **Default branch** | `main` (required by hellen-one automation) |

> **This is NOT [HELLCORE](https://github.com/quintinbannink42/HELLCORE).** HELLCORE is a separate project. PowerCore is a Hellen-One PDM carrier that matches the Link Razor loom connector.

Former working names (docs/history only): `hellen-pdm-razor`, Hellen Razor-class PDM.

## Docs

| File | Contents |
|------|----------|
| [POWERCORE_BRIEF.md](POWERCORE_BRIEF.md) | Product identity, tokens, Razor loom compatibility |
| [CONNECTOR.md](CONNECTOR.md) | Exact Razor-compatible 26-pin + M6 pinout (authoritative) |
| [PINMAP.md](PINMAP.md) | mega-mcu144 edge → HP / ADIO / system nets |
| [REV1_SPEC.md](REV1_SPEC.md) | Goals, architecture, e-fuse behaviour |
| [BLOCK_DIAGRAM.md](BLOCK_DIAGRAM.md) | Carrier block diagram |
| [BOARD.md](BOARD.md) | What’s stubbed vs next; module placement steps |
| [HARDWARE_BOM.md](HARDWARE_BOM.md) | Chosen PNs, kILIS, AmpsPerVolt TODOs |

## KiCad project

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

- `pdmrazora.kicad_pro` / `.kicad_sch` / `.kicad_pcb` (no dashes/underscores — hellen-one requirement)
- `revision.txt` → `BOARD_PREFIX=pdm` `BOARD_SUFFIX=razor` `BOARD_REVISION=a`

Schematic: SuperSeal **TE 6473418-1** vertical (Link Razor-compatible nets; same pin numbers as former RA 9-6437287-8), **split** M6 bolt-through bobbins (J2 VBAT+ north / J3 GND south, drivers between) + power entry/IGN_SW divider, sheets **MM144** / **HP** (**BTS50010-1TAD** ×4) / **ADIO** (**BTS7004-1EPP** ×8 + sense/PU). PCB: **109×98 mm** frame (was 104×93), mega-mcu144 0.7 west of a vertical SuperSeal EMI wall, power/PROFET east. J2 VBAT+ and J3 GND stay on opposite edges of the power field; HP×4 and ADIO×8 are mirrored about x=80. `PWR_OUT1–4` run on exposed F.Cu (F.Mask opened over the copper) with short B.Cu hops only at the module pad wall. DRC shorts/crossings/clearance are 0; the board is not fab-clean (see [BOARD.md](BOARD.md)). Parts/kILIS: [HARDWARE_BOM.md](HARDWARE_BOM.md).

## How to build (Hellen-One)

1. `git clone --recurse-submodules https://github.com/quintinbannink42/hellen-pdm-razor.git`
2. Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.
   Open `pdmrazora.kicad_pro`.
3. mega-mcu144 **0.7** is already on the frame (`M1000`). Refresh from `hellen-one/modules/mega-mcu144/0.7/` if the submodule moves.
4. Route SuperSeal / M6 / module pads per CONNECTOR.md / PINMAP.md; replace HP/ADIO schematic stubs with chosen PNs + sense parts.
5. Push to **`main`**. GitHub Action `.github/workflows/create-board.yaml` calls hellen-one create-board to merge module gerbers into `boards/`.
6. Daily workflows keep `hellen-one` and `kicad6-libraries` submodule refs updated.

Frame rules (from hellen-example FAQ):

- No `-` or `_` in KiCad filenames
- `aux_axis_origin` required; board origin at **bottom-left** (no negative coordinates)

## Firmware intent

Firmware is **not** this repo. See **[fw-powercore](https://github.com/quintinbannink42/fw-powercore)** (rusEFI custom board overlay: electronic fuse + channel map), based on [fw-custom-hellen144-f4](https://github.com/rusefi/fw-custom-hellen144-f4) / `hellen-common-mega144.mk`, with `protected_gpio` for HP1–4 + ADIO1–4 first. See PINMAP.md and REV1_SPEC.md.

## Submodules

```
hellen-one          https://github.com/andreika-git/hellen-one
kicad6-libraries    https://github.com/rusefi/kicad6-libraries
```

Skeleton mirrors [rusefi/hellen-example](https://github.com/rusefi/hellen-example).
