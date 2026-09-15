# Rev 1 carrier block diagram

```mermaid
flowchart TB
  subgraph Power["Power entry"]
    VBAT[VBAT / main terminals]
    TVS[TVS + reverse + input fuse]
    VSENSE[VBATT sense divider]
    VBAT --> TVS --> RAILS
    TVS --> VSENSE
  end

  subgraph RAILS["Rails"]
    VLOAD[VLOAD switched / fused feed]
    VLOGIC[Module logic from MM144]
    V5[5V sensor switched via PWR_EN]
  end

  subgraph HP["High-power x4"]
    HPDRV[PROFET / half-bridge stage]
    HPIS[IS current sense]
    HPOUT[HP1..HP4 dual SuperSeal pins]
    VLOAD --> HPDRV --> HPOUT
    HPDRV --> HPIS
  end

  subgraph ADIO["ADIO x8"]
    ADIODRV[8A high-side]
    ADIOMUX[Pin mux: out / ain / din]
    ADIOPU[Soft 4k7 pull-up]
    ADIOS[Sense V and/or I]
    ADIOCONN[ADIO1..ADIO8]
    VLOAD --> ADIODRV --> ADIOMUX --> ADIOCONN
    ADIOPU --> ADIOMUX
    ADIOMUX --> ADIOS
  end

  subgraph MCU["mega-mcu144 STM32F767"]
    GPIO[EN / PWM / DIR / PU GPIO]
    ADC[ADC bank]
    USB[USB-C]
    CAN[CAN]
  end

  GPIO --> HPDRV
  GPIO --> ADIODRV
  GPIO --> ADIOPU
  HPIS --> ADC
  ADIOS --> ADC
  VSENSE --> ADC
