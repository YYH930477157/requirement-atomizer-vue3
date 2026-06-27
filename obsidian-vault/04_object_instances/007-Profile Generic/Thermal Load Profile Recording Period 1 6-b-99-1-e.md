---
id: KB-OBIS-6-B-99-1-E-THERMAL-LOAD-PROFILE-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Thermal load profile recording period 1
aliases:
- Thermal load profile 6-b:99.1.e
- Thermal energy profile recording period 1
keywords:
- 6-b:99.1.e
- thermal load profile recording period 1
- thermal energy load profile
- Profile generic thermal
domain_tags:
- cosem_object
- thermal_energy
- load_profile
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-48
---

# Thermal load profile recording period 1

## Definition

Pattern-level row entry for thermal energy load profile objects with recording period 1, represented by OBIS pattern `6-b:99.1.e`.

## Aliases

- Thermal load profile 6-b:99.1.e
- Thermal energy profile recording period 1

## Domain Tags

- `cosem_object`
- `thermal_energy`
- `load_profile`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-48`

## Structured Data

```json metadata
{
  "obis_pattern": "6-b:99.1.e",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "thermal_energy",
  "value_group_mapping": {
    "A": "6 thermal energy",
    "B": "b channel selector",
    "C": "99 data profile objects",
    "D": "1 load profile with recording period 1",
    "E": "e profile selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 48,
    "title": "OBIS codes for data profile objects - Thermal energy"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 48 data profile objects - Thermal energy"
    }
  ],
  "applicable_notes": [
    "Use this pattern for thermal load profile objects captured with recording period 1.",
    "The Profile generic buffer and capture_objects determine the concrete captured quantities."
  ]
}
```

## Notes

