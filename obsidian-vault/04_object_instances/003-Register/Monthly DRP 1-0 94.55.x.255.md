---
id: KB-ABNT-OBIS-1-0-94-55-X-255-MONTHLY-DRP
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Monthly DRP
aliases:
- OBIS 1-0:94.55.x.255
- DRP calculation monthly
keywords:
- 1-0:94.55.x.255
- Monthly DRP
- DRP calculation monthly
- TBL-000145
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# Monthly DRP

## Definition

Row-level Register object at logical name `1-0:94.55.x.255`. Monthly DRP.

## Aliases

- OBIS 1-0:94.55.x.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55",
    "E": "x tariff/rate index (templated)",
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
      "section": "Table 24 OBIS codes for data profile objects - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Monthly DRP at 1-0:94.55.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about monthly drp.",
    "ABNT Appendix 9 describes this object as: Monthly DRP."
  ]
}
```

## Notes
