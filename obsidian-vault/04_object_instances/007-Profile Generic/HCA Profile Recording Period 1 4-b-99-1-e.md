---
id: KB-OBIS-4-B-99-1-E-HCA-PROFILE-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: HCA profile recording period 1
aliases:
- HCA profile 4-b:99.1.e
- Heat cost allocator profile recording period 1
keywords:
- 4-b:99.1.e
- HCA profile recording period 1
- heat cost allocator profile
- Profile generic HCA
domain_tags:
- cosem_object
- hca
- heat_cost_allocator
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-40
---

# HCA profile recording period 1

## Definition

Pattern-level row entry for heat cost allocator data profile objects with recording period 1, represented by OBIS pattern `4-b:99.1.e`.

## Aliases

- HCA profile 4-b:99.1.e
- Heat cost allocator profile recording period 1

## Domain Tags

- `cosem_object`
- `hca`
- `heat_cost_allocator`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-40`

## Structured Data

```json metadata
{
  "obis_pattern": "4-b:99.1.e",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "hca",
  "value_group_mapping": {
    "A": "4 heat cost allocator",
    "B": "b channel selector",
    "C": "99 data profile objects",
    "D": "1 profile with recording period 1",
    "E": "e profile selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 40,
    "title": "OBIS codes for data profile objects - HCA"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 40 data profile objects - HCA"
    }
  ],
  "applicable_notes": [
    "Use this pattern for HCA profile generic objects captured with recording period 1.",
    "The Profile generic capture_objects list defines the concrete captured HCA quantities."
  ]
}
```

## Notes

