---
id: KB-OBIS-1-0-94-55-194-255-MONTHLY-DRC-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Monthly DRC Log
aliases:
- Monthly DRC log 1-0:94.55.194.255
- DRC monthly log
keywords:
- 1-0:94.55.194.255
- Monthly DRC Log
- Monthly DRC log
- DRC log monthly
domain_tags:
- cosem_object
- ac_electricity
- power_quality
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# Monthly DRC Log

## Definition

Row-level AC Profile generic object for monthly DRC logging, represented by OBIS `1-0:94.55.194.255`.

## Aliases

- Monthly DRC log 1-0:94.55.194.255
- DRC monthly log

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.194.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 aggregate channel",
    "C": "94 utility-specific AC objects",
    "D": "55 monthly power-quality log group",
    "E": "194 monthly DRC log",
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
      "section": "Monthly DRC Log at 1-0:94.55.194.255"
    }
  ],
  "applicable_notes": [
    "Use this row for monthly DRC log requirements in ABNT power-quality contexts.",
    "ABNT Appendix 9 describes this object as the monthly DRC log."
  ]
}
```

## Notes

