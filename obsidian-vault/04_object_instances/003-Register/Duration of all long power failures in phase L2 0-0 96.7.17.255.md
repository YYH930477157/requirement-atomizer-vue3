---
id: KB-ABNT-OBIS-0-0-96-7-17-255-DURATION-OF-ALL-LONG-POWER-FAILURES-IN-PHASE-L2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Duration of all long power failures in phase L2
aliases:
- OBIS 0-0:96.7.17.255
- time for all long power outages, from the origin, in Phase B
keywords:
- 0-0:96.7.17.255
- Duration of all long power failures in phase L2
- time for all long power outages, from the origin, in Phase B
- TBL-000048
domain_tags:
- cosem_object
- general
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Duration of all long power failures in phase L2

## Definition

Row-level Register object at logical name `0-0:96.7.17.255`. Cumulative time for all long power outages, from the origin, in phase B (L2)

## Aliases

- OBIS 0-0:96.7.17.255

## Domain Tags

- `cosem_object`
- `general`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.7.17.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "96 abstract general data objects",
    "D": "7 power failure counters",
    "E": "17 cumulative long power-failure duration (phase L2)",
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
      "section": "Duration of all long power failures in phase L2 at 0-0:96.7.17.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about cumulative time for all long power outages.",
    "ABNT Appendix 9 describes this object as: cumulative time for all long power outages, from the origin, in phase B (L2)."
  ]
}
```

## Notes
