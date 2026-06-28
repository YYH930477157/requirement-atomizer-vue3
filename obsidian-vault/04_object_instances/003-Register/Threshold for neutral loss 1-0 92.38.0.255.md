---
id: KB-ABNT-OBIS-1-0-92-38-0-255-THRESHOLD-FOR-NEUTRAL-LOSS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Threshold for neutral loss
aliases:
- OBIS 1-0:92.38.0.255
keywords:
- 1-0:92.38.0.255
- Threshold for neutral loss
- TBL-000167
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Threshold for neutral loss

## Definition

Row-level Register object at logical name `1-0:92.38.0.255`. Threshold for neutral loss.

## Aliases

- OBIS 1-0:92.38.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:92.38.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "92 neutral loss",
    "D": "38 threshold (loss)",
    "E": "0 no tariff/total value",
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
      "section": "Threshold for neutral loss at 1-0:92.38.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about threshold for neutral loss.",
    "ABNT Appendix 9 describes this object as: Threshold for neutral loss."
  ]
}
```

## Notes
