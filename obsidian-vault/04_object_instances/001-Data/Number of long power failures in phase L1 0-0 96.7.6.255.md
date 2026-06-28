---
id: KB-ABNT-OBIS-0-0-96-7-6-255-NUMBER-OF-LONG-POWER-FAILURES-IN-PHASE-L1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Number of long power failures in phase L1
aliases:
- OBIS 0-0:96.7.6.255
keywords:
- 0-0:96.7.6.255
- Number of long power failures in phase L1
- TBL-000049
domain_tags:
- cosem_object
- general
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Number of long power failures in phase L1

## Definition

Row-level Data object at logical name `0-0:96.7.6.255`. Number of long power failures in phase L1

## Aliases

- OBIS 0-0:96.7.6.255

## Domain Tags

- `cosem_object`
- `general`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.7.6.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "96 abstract general data objects",
    "D": "7 power failure counters",
    "E": "6 long power-failure count (phase L1)",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 9,
    "title": "OBIS codes for error registers, alarm registers and alarm filters - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 9 OBIS codes for error registers, alarm registers and alarm filters - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Number of long power failures in phase L1 at 0-0:96.7.6.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about number of long power failures in phase l1.",
    "ABNT Appendix 9 describes this object as: number of long power failures in phase L1."
  ]
}
```

## Notes
