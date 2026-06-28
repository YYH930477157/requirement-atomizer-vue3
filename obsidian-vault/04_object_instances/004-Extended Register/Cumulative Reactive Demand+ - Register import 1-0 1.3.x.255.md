---
id: KB-ABNT-OBIS-1-0-1-3-X-255-CUMULATIVE-REACTIVE-DEMAND-REGISTER-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Cumulative Reactive Demand+ - Register import
aliases:
- OBIS 1-0:1.3.x.255
keywords:
- 1-0:1.3.x.255
- Cumulative Reactive Demand+ - Register import
- TBL-000097
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Cumulative Reactive Demand+ - Register import

## Definition

Row-level Extended Register object at logical name `1-0:1.3.x.255`. Cumulative Reactive Demand+ - Register import.

## Aliases

- OBIS 1-0:1.3.x.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-4-EXTENDED-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:1.3.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "1 active energy (+A import)",
    "D": "3 cumulative",
    "E": "x tariff/rate index (templated)",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 14,
    "title": "Value group D codes - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 14 Value group D codes - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Cumulative Reactive Demand+ - Register import at 1-0:1.3.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about cumulative reactive demand+ - register import.",
    "ABNT Appendix 9 describes this object as: Cumulative Reactive Demand+ - Register import."
  ]
}
```

## Notes
