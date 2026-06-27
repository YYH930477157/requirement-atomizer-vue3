---
id: KB-OBIS-8-B-99-1-E-WATER-LOAD-PROFILE-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Water load profile recording period 1
aliases:
- Cold water load profile 8-b:99.1.e
- Water profile recording period 1
keywords:
- 8-b:99.1.e
- water load profile recording period 1
- cold water load profile
- Profile generic water
domain_tags:
- cosem_object
- water
- load_profile
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-71
---

# Water load profile recording period 1

## Definition

Pattern-level row entry for water load profile objects with recording period 1, represented by OBIS pattern `8-b:99.1.e`.

## Aliases

- Cold water load profile 8-b:99.1.e
- Water profile recording period 1

## Domain Tags

- `cosem_object`
- `water`
- `load_profile`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-71`

## Structured Data

```json metadata
{
  "obis_pattern": "8-b:99.1.e",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "water",
  "value_group_mapping": {
    "A": "8 cold water",
    "B": "b channel selector",
    "C": "99 data profile objects",
    "D": "1 load profile with recording period 1",
    "E": "e profile selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 71,
    "title": "OBIS codes for data profile objects - Water"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 71 data profile objects - Water"
    }
  ],
  "applicable_notes": [
    "Use this pattern for water load profile objects captured with recording period 1.",
    "The Profile generic buffer and capture_objects determine the concrete captured quantities."
  ]
}
```

## Notes

