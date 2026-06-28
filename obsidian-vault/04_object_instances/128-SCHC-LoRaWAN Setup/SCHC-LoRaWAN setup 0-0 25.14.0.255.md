---
id: KB-ABNT-OBIS-0-0-25-14-0-255-SCHC-LORAWAN-SETUP
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: SCHC-LoRaWAN setup
aliases:
- OBIS 0-0:25.14.0.255
keywords:
- 0-0:25.14.0.255
- SCHC-LoRaWAN setup
- schc lorawan setup
- TBL-000075
domain_tags:
- cosem_object
- general
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# SCHC-LoRaWAN setup

## Definition

Row-level SCHC-LoRaWAN Setup object at logical name `0-0:25.14.0.255`, configuring the LPWAN profile for a LoRaWAN lower layer.

## Aliases

- OBIS 0-0:25.14.0.255

## Domain Tags

- `cosem_object`
- `general`
- `communication_profile`

## Relations

- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:25.14.0.255",
  "likely_interface_class_id": 128,
  "likely_interface_class_name": "SCHC-LoRaWAN Setup",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "25 LPWAN/M-Bus port setup",
    "D": "14 SCHC-LoRaWAN setup",
    "E": "0",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "SCHC-LoRaWAN setup at 0-0:25.14.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements that set up or diagnose the SCHC/LoRaWAN LPWAN communication profile.",
    "ABNT Appendix 9 registers this object as the SCHC-LoRaWAN setup (interface class 128) for the meter."
  ]
}
```

## Notes
