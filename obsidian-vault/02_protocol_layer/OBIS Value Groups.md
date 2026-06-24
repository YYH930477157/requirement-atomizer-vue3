---
id: KB-BLUE-BOOK-OBIS-VALUE-GROUPS
kb_id: obsidian_energy_metering
type: code_structure
layer: object_model
name: OBIS Value Groups
aliases:
- OBIS A-B:C.D.E.F
- OBIS value group
- OBIS code structure
- A-B:C.D.E.F
keywords:
- obis value group
- value group a
- value group b
- value group c
- value group d
- value group e
- value group f
- a-b:c.d.e.f
- billing period
- tariff rate
- medium
- measurement channel
domain_tags:
- obis_code
- blue_book
- cosem_object
- data_model
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-1-OBIS
- relation: identifies
  target: KB-L2-OBIS-LOGICAL-NAME
---

# OBIS Value Groups

## Definition

OBIS logical names use six value groups in the A-B:C.D.E.F structure. The groups identify media, channels, data items, processing or classification, tariff or further processing, and historical or billing period allocation.

## Aliases

- OBIS A-B:C.D.E.F
- OBIS value group
- OBIS code structure
- A-B:C.D.E.F

## Domain Tags

- `obis_code`
- `blue_book`
- `cosem_object`
- `data_model`

## Structured Data

```json metadata
{
  "format": "A-B:C.D.E.F",
  "groups": [
    {
      "group": "A",
      "meaning": "Media or energy type; A=0 is abstract, A=1 AC electricity, A=2 DC electricity, A=4 heat cost allocator, A=5/6 thermal energy, A=7 gas, A=8 cold water, A=9 hot water."
    },
    {
      "group": "B",
      "meaning": "Measurement or communication channel; B=0 means no channel specified, B=1..64 channel numbers."
    },
    {
      "group": "C",
      "meaning": "Abstract or physical data item such as current, voltage, power, volume, temperature, list object, or data profile object."
    },
    {
      "group": "D",
      "meaning": "Type, result of processing, or further classification for the item identified by A to C."
    },
    {
      "group": "E",
      "meaning": "Tariff rate or other further classification, depending on the medium-specific object family."
    },
    {
      "group": "F",
      "meaning": "Billing period, historical value, or other storage instance allocation."
    }
  ],
  "standard_ranges": {
    "manufacturer_specific": "Selected ranges such as 128..199 or 128..254 depending on value group and context.",
    "utility_specific": "Selected ranges such as B=65..127.",
    "consortia_specific": "C or D code 93 context.",
    "country_specific": "C or D code 94 context."
  }
}
```

## Notes

