---
id: KB-OBIS-4-B-98-1-E-255-HCA-BILLING-LIST-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: HCA billing period list 1
aliases:
- HCA billing list 1
- Heat cost allocator billing period list 1
- OBIS 4-b:98.1.e.255
keywords:
- 4-b:98.1.e.255
- HCA billing period list 1
- heat cost allocator billing list
- HCA list object
domain_tags:
- cosem_object
- hca
- heat_cost_allocator
- billing
- list_object
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-39
---

# HCA billing period list 1

## Definition

Pattern-level row entry for heat cost allocator billing period list objects, represented by OBIS pattern `4-b:98.1.e.255`.

## Aliases

- HCA billing list 1
- Heat cost allocator billing period list 1
- OBIS 4-b:98.1.e.255

## Domain Tags

- `cosem_object`
- `hca`
- `heat_cost_allocator`
- `billing`
- `list_object`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-39`

## Structured Data

```json metadata
{
  "obis_pattern": "4-b:98.1.e.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "hca",
  "value_group_mapping": {
    "A": "4 heat cost allocator",
    "B": "b channel selector",
    "C": "98 list objects",
    "D": "1 billing period list 1",
    "E": "e list selector",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 39,
    "title": "OBIS codes for list objects - HCA"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 39 list objects - HCA"
    }
  ],
  "applicable_notes": [
    "Use this pattern for heat cost allocator list objects that hold billing-period data.",
    "The B and E groups select the concrete channel and list variant."
  ]
}
```

## Notes

