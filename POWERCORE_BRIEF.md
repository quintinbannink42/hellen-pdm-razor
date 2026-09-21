# PowerCore — product brief

**Product:** PowerCore (standalone automotive power distribution module)  
**Hardware repo:** `hellen-pdm-razor` (legacy GitHub path; **product name is PowerCore**)  
**KiCad stem:** `pdmrazora` (hellen-one: no dashes/underscores — **do not rename**)  
**Firmware:** [fw-powercore](https://github.com/quintinbannink42/fw-powercore)  
**MCU module:** Hellen mega-mcu144 (STM32F767), rev ≥ 0.7  
**Loom / connector:** Link **Razor PDM**-compatible AMP SuperSeal 1.0 26-pin (Link “Connector C”) + M6 main power  

**Not:** [HELLCORE](https://github.com/quintinbannink42/HELLCORE), Micro Core, or an engine ECU.

Former working names (docs/history only): `hellen-pdm-razor`, Hellen Razor-class PDM.

## What it is

PowerCore is a Hellen-One **carrier** that distributes battery power through programmable high-side channels, with TunerStudio as a **PDM** environment (outputs, current, trips, CAN), not a full ECU page set.

Rev 1 I/O:

- 4× high-power (25 A continuous / 80 A peak class)
- 8× ADIO (8 A high-side, analog/digital in, software pull-ups)
- USB + CAN; electronic-fuse behaviour in firmware
- Drop-in **connector and loom compatibility** with the Link ECU Razor PDM SuperSeal pinout

## Identity tokens (do not mix)

| Layer | Token | Notes |
|-------|-------|-------|
| Product | **PowerCore** | User-facing name |
| GitHub hardware | `hellen-pdm-razor` | Legacy repo path; clone URL unchanged |
| KiCad / hellen-one | `pdmrazora` | `BOARD_PREFIX=pdm` `BOARD_SUFFIX=razor` `BOARD_REVISION=a` |
| Firmware | `powercore` | `SHORT_BOARD_NAME` / `FIRMWARE_ID` in fw-powercore |

## Hardware ownership

This repo owns the Hellen-One frame, SuperSeal header, PROFET stages, and pinout docs. Firmware lives in **fw-powercore**. Do not invent pins: [PINMAP.md](PINMAP.md), [CONNECTOR.md](CONNECTOR.md), [REV1_SPEC.md](REV1_SPEC.md), [HARDWARE_BOM.md](HARDWARE_BOM.md).

## Out of scope

- Renaming KiCad files away from `pdmrazora`
- Mixing with HELLCORE or Micro Core streams
- Sealed Link-style CNC housing / “PDM Link” clone UI (rev 1 non-goal)
