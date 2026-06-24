---
id: KB-OBIS-2-B-97-97-E-DC-ERROR-REGISTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC error register
aliases:
- DC error register 2-b:97.97.e
- DC electricity error register
keywords:
- 2-b:97.97.e
- DC error register
- DC electricity error register
- error register DC
domain_tags:
- cosem_object
- dc_electricity
- error
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-30
---

# DC error register

## Definition

Pattern-level row entry for DC electricity error register objects using OBIS pattern `2-b:97.97.e`.

## Aliases

- DC error register 2-b:97.97.e
- DC electricity error register

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `error`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-30`

## Structured Data

```json metadata
{
  "obis_pattern": "2-b:97.97.e",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "b channel selector",
    "C": "97 error register objects",
    "D": "97 error register",
    "E": "e error register selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 30,
    "title": "OBIS codes for error register objects - DC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 30 error register objects - DC electricity"
    }
  ],
  "applicable_notes": [
    "The Blue Book table does not define the specific information included in error objects.",
    "Use companion specifications or project profiles to interpret concrete bit assignments."
  ]
}
```

## Notes

