---
id: KB-OBIS-1-B-99-1-E-AC-LOAD-PROFILE-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: AC load profile recording period 1
aliases:
- AC load profile 1-b:99.1.e
- Load profile with recording period 1 AC
keywords:
- 1-b:99.1.e
- AC load profile recording period 1
- load profile with recording period 1 AC
- AC electricity load profile
domain_tags:
- cosem_object
- ac_electricity
- load_profile
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# AC load profile recording period 1

## Definition

Pattern-level row entry for AC electricity load profile objects with recording period 1, represented by OBIS pattern `1-b:99.1.e`.

## Aliases

- AC load profile 1-b:99.1.e
- Load profile with recording period 1 AC

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `load_profile`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`

## Structured Data

```json metadata
{
  "obis_pattern": "1-b:99.1.e",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "b channel selector",
    "C": "99 data profile objects",
    "D": "1 load profile with recording period 1",
    "E": "e profile selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 24,
    "title": "OBIS codes for data profile objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 24 data profile objects - AC electricity"
    }
  ],
  "applicable_notes": [
    "Use this pattern for AC load profile objects captured with recording period 1.",
    "The Profile generic buffer and capture_objects determine the concrete captured quantities."
  ]
}
```

## Notes

