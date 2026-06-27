---
id: KB-OBIS-0-0-21-0-6-255-INSTANT-VALUES
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instant Values
aliases:
- Instant values profile 0-0:21.0.6.255
- Values snapshots
keywords:
- 0-0:21.0.6.255
- Instant Values
- values snapshots
- instant values profile
domain_tags:
- cosem_object
- snapshot
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-12
---

# Instant Values

## Definition

Row-level abstract Profile generic object for instantaneous value snapshots, represented by OBIS `0-0:21.0.6.255`.

## Aliases

- Instant values profile 0-0:21.0.6.255
- Values snapshots

## Domain Tags

- `cosem_object`
- `snapshot`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-12`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:21.0.6.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "21 instantaneous value profile group",
    "D": "0 aggregate channel",
    "E": "6 instant values",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 12,
    "title": "OBIS codes for data profile objects - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 12 data profile objects - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Instant Values at 0-0:21.0.6.255"
    }
  ],
  "applicable_notes": [
    "Use this row when instantaneous value snapshots are retained through a Profile generic object.",
    "The captured values are determined by the object's capture_objects attribute."
  ]
}
```

## Notes

