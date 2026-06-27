---
id: KB-OBIS-4-B-97-97-E-HCA-ERROR-REGISTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: HCA error register
aliases:
- HCA error register 4-b:97.97.e
- Heat cost allocator error register
keywords:
- 4-b:97.97.e
- HCA error register
- heat cost allocator error register
- error register HCA
domain_tags:
- cosem_object
- hca
- heat_cost_allocator
- error
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-38
---

# HCA error register

## Definition

Pattern-level row entry for heat cost allocator error register objects using OBIS pattern `4-b:97.97.e`.

## Aliases

- HCA error register 4-b:97.97.e
- Heat cost allocator error register

## Domain Tags

- `cosem_object`
- `hca`
- `heat_cost_allocator`
- `error`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-38`

## Structured Data

```json metadata
{
  "obis_pattern": "4-b:97.97.e",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "hca",
  "value_group_mapping": {
    "A": "4 heat cost allocator",
    "B": "b channel selector",
    "C": "97 error register objects",
    "D": "97 error register",
    "E": "e error register selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 38,
    "title": "OBIS codes for error register objects - HCA"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 38 error register objects - HCA"
    }
  ],
  "applicable_notes": [
    "The Blue Book table identifies the HCA error-register object family.",
    "Concrete bit assignments remain project/profile specific."
  ]
}
```

## Notes

