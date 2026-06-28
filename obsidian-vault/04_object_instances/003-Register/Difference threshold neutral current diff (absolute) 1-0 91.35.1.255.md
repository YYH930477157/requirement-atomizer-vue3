---
id: KB-ABNT-OBIS-1-0-91-35-1-255-DIFFERENCE-THRESHOLD-NEUTRAL-CURRENT-DIFF-ABSOLUTE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Difference threshold neutral current diff (absolute)
aliases:
- OBIS 1-0:91.35.1.255
keywords:
- 1-0:91.35.1.255
- Difference threshold neutral current diff (absolute)
- TBL-000168
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Difference threshold neutral current diff (absolute)

## Definition

Row-level Register object at logical name `1-0:91.35.1.255`. Difference threshold neutral current diff (absolute).

## Aliases

- OBIS 1-0:91.35.1.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:91.35.1.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "91 neutral current",
    "D": "35 threshold",
    "E": "1 no tariff/total value",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 13,
    "title": "Value group C codes - AC Electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 13 Value group C codes - AC Electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Difference threshold neutral current diff (absolute) at 1-0:91.35.1.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about difference threshold neutral current diff (absolute).",
    "ABNT Appendix 9 describes this object as: Difference threshold neutral current diff (absolute)."
  ]
}
```

## Notes
