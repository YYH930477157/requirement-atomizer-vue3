---
id: KB-OBIS-7-B-97-97-E-GAS-ERROR-REGISTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas error register
aliases:
- Gas error register 7-b:97.97.e
- Gas meter error register
keywords:
- 7-b:97.97.e
- gas error register
- gas meter error register
- error register gas
domain_tags:
- cosem_object
- gas
- error
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-62
---

# Gas error register

## Definition

Pattern-level row entry for gas error register objects using OBIS pattern `7-b:97.97.e`.

## Aliases

- Gas error register 7-b:97.97.e
- Gas meter error register

## Domain Tags

- `cosem_object`
- `gas`
- `error`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-62`

## Structured Data

```json metadata
{
  "obis_pattern": "7-b:97.97.e",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "b channel selector",
    "C": "97 error register objects",
    "D": "97 error register",
    "E": "e error register selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 62,
    "title": "OBIS codes for error register objects - Gas"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 62 error register objects - Gas"
    }
  ],
  "applicable_notes": [
    "The Blue Book table identifies the gas error-register object family.",
    "Concrete bit assignments remain project/profile specific."
  ]
}
```

## Notes

