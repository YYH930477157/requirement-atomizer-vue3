---
id: KB-ABNT-OBIS-1-0-0-1-1-255-NUMBER-OF-AVAILABLE-BILLING-PERIODS-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Number of available billing periods
aliases:
- OBIS 1-0:0.1.1.255
keywords:
- 1-0:0.1.1.255
- Number of available billing periods (1)
- TBL-000103
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-21
---

# Number of available billing periods

## Definition

Row-level Data object at logical name `1-0:0.1.1.255`. Number of available billing periods

## Aliases

- OBIS 1-0:0.1.1.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-21`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:0.1.1.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "0 general and service-entry object",
    "D": "1 billing period/identifier",
    "E": "1 tariff/rate 1",
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
      "section": "Number of available billing periods at 1-0:0.1.1.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about number of available billing periods.",
    "ABNT Appendix 9 describes this object as: number of available billing periods."
  ]
}
```

## Notes
