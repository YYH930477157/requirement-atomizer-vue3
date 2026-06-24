---
id: KB-OBIS-1-B-97-97-E-AC-ERROR-REGISTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: AC error register
aliases:
- AC error register 1-b:97.97.e
- AC electricity error register
keywords:
- 1-b:97.97.e
- AC error register
- AC electricity error register
- error register AC
domain_tags:
- cosem_object
- ac_electricity
- error
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-22
---

# AC error register

## Definition

Pattern-level row entry for AC electricity error register objects using OBIS pattern `1-b:97.97.e`.

## Aliases

- AC error register 1-b:97.97.e
- AC electricity error register

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `error`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-22`

## Structured Data

```json metadata
{
  "obis_pattern": "1-b:97.97.e",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "b channel selector",
    "C": "97 error register objects",
    "D": "97 error register",
    "E": "e error register selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 22,
    "title": "OBIS codes for error register objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 22 error register objects - AC electricity"
    }
  ],
  "applicable_notes": [
    "The Blue Book table does not define the specific information included in error objects.",
    "Use companion specifications or project profiles to interpret concrete bit assignments."
  ]
}
```

## Notes

