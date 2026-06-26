---
id: KB-OBIS-1-0-1-8-3-255-TARIFF-RATE3
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active energy import Rate 3 tariff
aliases:
- Tariff Rate 3 active energy import
- OBIS 1-0:1.8.3.255
keywords:
- 1-0:1.8.3.255
- tariff rate 3
- active energy import rate 3
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

# Active energy import Rate 3 tariff

## Definition

Row-level OBIS object for AC electricity active energy import under tariff rate 3. Pattern 1-0:1.8.3.255.

## Aliases

- Tariff Rate 3 active energy import
- OBIS 1-0:1.8.3.255

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
  "obis_pattern": "1-0:1.8.3.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "1 active energy import",
    "D": "8 time integral 1",
    "E": "3 rate 3",
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
      "section": "Table 15 AC electricity tariff rates; E=3 Rate 3"
    }
  ],
  "applicable_notes": [
    "E=3 identifies Rate 3 per Blue Book Table 15."
  ]
}
```

## Notes

