---
id: KB-OBIS-2-B-99-98-E-DC-EVENT-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC event log profile
aliases:
- DC event log 2-b:99.98.e
- DC electricity event log profile
keywords:
- 2-b:99.98.e
- DC event log profile
- DC electricity event log
- Profile generic DC event log
domain_tags:
- cosem_object
- dc_electricity
- event
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-32
---

# DC event log profile

## Definition

Pattern-level row entry for DC electricity event log Profile generic objects using OBIS pattern `2-b:99.98.e`.

## Aliases

- DC event log 2-b:99.98.e
- DC electricity event log profile

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `event`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-32`

## Structured Data

```json metadata
{
  "obis_pattern": "2-b:99.98.e",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "b channel selector",
    "C": "99 data profile objects",
    "D": "98 event log",
    "E": "e profile selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 32,
    "title": "OBIS codes for data profile objects - DC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 32 data profile objects - DC electricity"
    }
  ],
  "applicable_notes": [
    "Use this pattern for DC-specific event logs.",
    "For event logs that hold non-energy-type-specific data, use the abstract event log profile pattern instead."
  ]
}
```

## Notes

