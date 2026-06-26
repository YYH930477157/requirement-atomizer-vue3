---
id: KB-OBIS-1-0-1-8-0-255-TARIFF-TOTAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active energy import Total tariff
aliases:
- Tariff Total active energy import
- OBIS 1-0:1.8.0.255
keywords:
- 1-0:1.8.0.255
- tariff total
- active energy import total
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

# Active energy import Total tariff

## Definition

Row-level OBIS object for AC electricity active energy import under total tariff. Pattern 1-0:1.8.0.255.

## Aliases

- Tariff Total active energy import
- OBIS 1-0:1.8.0.255

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
  "obis_pattern": "1-0:1.8.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "1 active energy import",
    "D": "8 time integral 1",
    "E": "0 total",
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
      "section": "Table 15 AC electricity tariff rates; E=0 Total"
    }
  ],
  "applicable_notes": [
    "E=0 identifies Total per Blue Book Table 15."
  ]
}
```

## Notes

