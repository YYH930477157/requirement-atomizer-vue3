---
id: KB-OBIS-1-0-1-31-0-255-AC-DCODE-31
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active energy import under limit threshold
aliases:
- OBIS 1-0:1.31.0.255
- active energy import under limit threshold
keywords:
- 1-0:1.31.0.255
- active energy import under limit threshold
- under limit threshold
- ac_electricity
domain_tags:
- cosem_object
- ac_electricity
- active_energy
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Active energy import under limit threshold

## Definition

Row-level OBIS object for AC electricity active energy import, threshold below which a quantity is considered under-limit. D=31 (Under limit threshold) per Blue Book Table 14. Pattern 1-0:1.31.0.255.

## Aliases

- OBIS 1-0:1.31.0.255
- active energy import under limit threshold

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `active_energy`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:1.31.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 ac_electricity",
    "B": "0 no channel",
    "C": "1 active energy import",
    "D": "31 under limit threshold",
    "E": "0 total",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 14,
    "title": "Value group D codes - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 14 AC electricity D codes; C=1, D=31 Under limit threshold, E=0"
    }
  ],
  "applicable_notes": [
    "D=31 identifies 'Under limit threshold' (threshold below which a quantity is considered under-limit)."
  ]
}
```

## Notes

