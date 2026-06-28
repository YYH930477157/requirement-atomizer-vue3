---
id: KB-ABNT-OBIS-1-0-0-1-2-255-TIME-STAMP-OF-BILLING-PERIOD-1-LAST-RESET
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Time stamp of billing period 1 last reset
aliases:
- OBIS 1-0:0.1.2.255
- Date/time of most recent billing period
keywords:
- 1-0:0.1.2.255
- Time stamp of billing period 1 last reset
- Date/time of most recent billing period
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

# Time stamp of billing period 1 last reset

## Definition

Row-level Data object at logical name `1-0:0.1.2.255`. Date/time of the most recent billing period reset

## Aliases

- OBIS 1-0:0.1.2.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-21`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:0.1.2.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "0 general and service-entry object",
    "D": "1 billing period/identifier",
    "E": "2 tariff/rate 2",
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
      "section": "Time stamp of billing period 1 last reset at 1-0:0.1.2.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about date/time of the most recent billing period reset.",
    "ABNT Appendix 9 describes this object as: date/time of the most recent billing period reset."
  ]
}
```

## Notes
