---
id: KB-ABNT-OBIS-1-0-9-51-0-255-S-MINIMUM-APPARENT-IMPORT-POWER-PERIOD-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: S+ Minimum apparent import power - period 1
aliases:
- OBIS 1-0:9.51.0.255
keywords:
- 1-0:9.51.0.255
- S+ Minimum apparent import power - period 1
- TBL-000165
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# S+ Minimum apparent import power - period 1

## Definition

Row-level Register object at logical name `1-0:9.51.0.255`. Minimum of apparent power (S+ import), period 1

## Aliases

- OBIS 1-0:9.51.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:9.51.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "9 apparent power (S+ import)",
    "D": "51 minimum - period 1",
    "E": "0 no tariff/total value",
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
      "section": "S+ Minimum apparent import power - period 1 at 1-0:9.51.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about minimum of apparent power (S+ import).",
    "ABNT Appendix 9 describes this object as: minimum of apparent power (S+ import), period 1."
  ]
}
```

## Notes
