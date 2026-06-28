---
id: KB-ABNT-OBIS-1-0-0-9-11-255-CLOCK-TIME-SHIFT-EVENT-LIMIT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Clock Time Shift Event Limit
aliases:
- OBIS 1-0:0.9.11.255
keywords:
- 1-0:0.9.11.255
- Clock Time Shift Event Limit
- TBL-000171
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-21
---

# Clock Time Shift Event Limit

## Definition

Row-level Register object at logical name `1-0:0.9.11.255`. Clock time-shift event limit

## Aliases

- OBIS 1-0:0.9.11.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-21`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:0.9.11.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "0 general and service-entry object",
    "D": "9 instantaneous/status",
    "E": "11",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 21,
    "title": "OBIS codes for general and service entry objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 21 OBIS codes for general and service entry objects - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Clock Time Shift Event Limit at 1-0:0.9.11.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about clock time-shift event limit.",
    "ABNT Appendix 9 describes this object as: clock time-shift event limit."
  ]
}
```

## Notes
