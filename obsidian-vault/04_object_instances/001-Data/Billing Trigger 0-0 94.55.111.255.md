---
id: KB-ABNT-OBIS-0-0-94-55-111-255-BILLING-TRIGGER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Billing Trigger
aliases:
- OBIS 0-0:94.55.111.255
keywords:
- 0-0:94.55.111.255
- Billing Trigger
- TBL-000072
domain_tags:
- cosem_object
- general
- billing
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Billing Trigger

## Definition

Row-level Data object at logical name `0-0:94.55.111.255`. Billing trigger object for the billing process

## Aliases

- OBIS 0-0:94.55.111.255

## Domain Tags

- `cosem_object`
- `general`
- `billing`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:94.55.111.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "111 billing trigger",
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
      "section": "Billing Trigger at 0-0:94.55.111.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about billing trigger object for the billing process.",
    "ABNT Appendix 9 describes this object as: billing trigger object for the billing process."
  ]
}
```

## Notes
