---
id: KB-ABNT-OBIS-0-0-94-55-102-255-DURATION-OF-CURRENT-LONG-POWER-FAILURES-IN-PHASE-L2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Duration of current long power failures in phase L2
aliases:
- OBIS 0-0:94.55.102.255
- time to failure current power (open) in Phase B
keywords:
- 0-0:94.55.102.255
- Duration of current long power failures in phase L2
- time to failure current power (open) in Phase B
- TBL-000049
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

# Duration of current long power failures in phase L2

## Definition

Row-level Register object at logical name `0-0:94.55.102.255`. Time to failure of current power in phase B (L2)

## Aliases

- OBIS 0-0:94.55.102.255

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
  "obis_pattern": "0-0:94.55.102.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "102 current long power-failure duration (phase L2)",
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
      "section": "Duration of current long power failures in phase L2 at 0-0:94.55.102.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about time to failure of current power in phase b (l2).",
    "ABNT Appendix 9 describes this object as: time to failure of current power in phase B (L2)."
  ]
}
```

## Notes
