---
id: KB-OBIS-1-0-99-1-0-255-LOAD-PROFILE-PERIOD-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Load profile and quality with period 1
aliases:
- Load profile period 1 1-0:99.1.0.255
- Load profiles and quality profiles period 1
keywords:
- 1-0:99.1.0.255
- Load profile and quality with period 1
- load profile period 1
- load profiles and quality profiles
domain_tags:
- cosem_object
- ac_electricity
- load_profile
- power_quality
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# Load profile and quality with period 1

## Definition

Row-level AC Profile generic object for load profile and quality captures with recording period 1, represented by OBIS `1-0:99.1.0.255`.

## Aliases

- Load profile period 1 1-0:99.1.0.255
- Load profiles and quality profiles period 1

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `load_profile`
- `power_quality`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:99.1.0.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 aggregate channel",
    "C": "99 load profile and quality profile objects",
    "D": "1 recording period 1",
    "E": "0 aggregate profile",
    "F": "255 current value"
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
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Load profile and quality with period 1 at 1-0:99.1.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row for AC load profile and quality-profile requirements using recording period 1.",
    "The Profile generic capture period and capture_objects determine the sampled quantities."
  ]
}
```

## Notes

