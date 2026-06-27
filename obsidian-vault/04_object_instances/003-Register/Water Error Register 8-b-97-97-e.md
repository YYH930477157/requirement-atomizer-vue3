---
id: KB-OBIS-8-B-97-97-E-WATER-ERROR-REGISTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Water error register
aliases:
- Cold water error register
- Water error register 8-b:97.97.e
keywords:
- 8-b:97.97.e
- water error register
- cold water error register
- error register water
domain_tags:
- cosem_object
- water
- error
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-69
---

# Water error register

## Definition

Pattern-level row entry for water error register objects using OBIS pattern `8-b:97.97.e`.

## Aliases

- Cold water error register
- Water error register 8-b:97.97.e

## Domain Tags

- `cosem_object`
- `water`
- `error`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-69`

## Structured Data

```json metadata
{
  "obis_pattern": "8-b:97.97.e",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "water",
  "value_group_mapping": {
    "A": "8 cold water",
    "B": "b channel selector",
    "C": "97 error register objects",
    "D": "97 error register",
    "E": "e error register selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 69,
    "title": "OBIS codes for error register objects - Water"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 69 error register objects - Water"
    }
  ],
  "applicable_notes": [
    "The Blue Book table identifies the water error-register object family.",
    "Concrete bit assignments remain project/profile specific."
  ]
}
```

## Notes

