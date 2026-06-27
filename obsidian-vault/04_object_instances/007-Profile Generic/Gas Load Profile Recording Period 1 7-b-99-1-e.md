---
id: KB-OBIS-7-B-99-1-E-GAS-LOAD-PROFILE-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas load profile recording period 1
aliases:
- Gas load profile 7-b:99.1.e
- Gas profile recording period 1
keywords:
- 7-b:99.1.e
- gas load profile recording period 1
- gas load profile
- Profile generic gas
domain_tags:
- cosem_object
- gas
- load_profile
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-64
---

# Gas load profile recording period 1

## Definition

Pattern-level row entry for gas load profile objects with recording period 1, represented by OBIS pattern `7-b:99.1.e`.

## Aliases

- Gas load profile 7-b:99.1.e
- Gas profile recording period 1

## Domain Tags

- `cosem_object`
- `gas`
- `load_profile`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-64`

## Structured Data

```json metadata
{
  "obis_pattern": "7-b:99.1.e",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "b channel selector",
    "C": "99 data profile objects",
    "D": "1 load profile with recording period 1",
    "E": "e profile selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 64,
    "title": "OBIS codes for data profile objects - Gas"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 64 data profile objects - Gas"
    }
  ],
  "applicable_notes": [
    "Use this pattern for gas load profile objects captured with recording period 1.",
    "The Profile generic buffer and capture_objects determine the concrete captured quantities."
  ]
}
```

## Notes

