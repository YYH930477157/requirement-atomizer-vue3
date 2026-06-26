---
id: KB-OBIS-1-0-1-8-4-255-TARIFF-RATE4
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active energy import Rate 4 tariff
aliases:
- Tariff Rate 4 active energy import
- OBIS 1-0:1.8.4.255
keywords:
- 1-0:1.8.4.255
- tariff rate 4
- active energy import rate 4
domain_tags:
- cosem_object
- ac_electricity
- active_energy
- tariff
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-15
---

# Active energy import Rate 4 tariff

## Definition

Row-level OBIS object for AC electricity active energy import under tariff rate 4. Pattern 1-0:1.8.4.255.

## Aliases

- Tariff Rate 4 active energy import
- OBIS 1-0:1.8.4.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `active_energy`
- `tariff`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-15`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:1.8.4.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "1 active energy import",
    "D": "8 time integral 1",
    "E": "4 rate 4",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 15,
    "title": "Value group E codes - AC electricity - Tariff rates"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 15 AC electricity tariff rates; E=4 Rate 4"
    }
  ],
  "applicable_notes": [
    "E=4 identifies Rate 4 per Blue Book Table 15."
  ]
}
```

## Notes

