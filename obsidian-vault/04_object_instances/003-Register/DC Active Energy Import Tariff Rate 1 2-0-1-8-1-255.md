---
id: KB-OBIS-2-0-1-8-1-255-DC-TARIFF-RATE1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC active energy import Rate 1 tariff
aliases:
- Tariff Rate 1 DC active energy import
- OBIS 2-0:1.8.1.255
keywords:
- 2-0:1.8.1.255
- tariff rate 1
- dc
- dc active energy import rate 1
domain_tags:
- cosem_object
- dc_electricity
- active_energy
- tariff
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-28
---

# DC active energy import Rate 1 tariff

## Definition

Row-level OBIS object for DC electricity active energy import under tariff Rate 1. Pattern 2-0:1.8.1.255.

## Aliases

- Tariff Rate 1 DC active energy import
- OBIS 2-0:1.8.1.255

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `active_energy`
- `tariff`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-28`

## Structured Data

```json metadata
{
  "obis_pattern": "2-0:1.8.1.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 dc_electricity",
    "B": "0",
    "C": "1 active energy import",
    "D": "8 time integral 1",
    "E": "1 rate 1",
    "F": "255"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 28,
    "title": "Value group E codes - DC electricity - Tariff rates"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 28 DC electricity tariff rates; E=1 Rate 1"
    }
  ],
  "applicable_notes": [
    "E=1 identifies Rate 1 per Blue Book Table 28."
  ]
}
```

## Notes

