---
id: KB-ABNT-OBIS-0-0-44-1-0-255-KEY-EXPIRATION-CONTROL-FUNCTION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Key expiration control function
aliases:
- OBIS 0-0:44.1.0.255
- Controls enabling/disabling of the key check function
keywords:
- 0-0:44.1.0.255
- Key expiration control function
- key check function
- key expiration
- TBL-000074
domain_tags:
- cosem_object
- general
- security
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Key expiration control function

## Definition

Row-level Key Expiration Control Function object at logical name `0-0:44.1.0.255`, controlling enabling/disabling of the key check function.

## Aliases

- OBIS 0-0:44.1.0.255
- Controls enabling/disabling of the key check function

## Domain Tags

- `cosem_object`
- `general`
- `security`

## Relations

- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:44.1.0.255",
  "likely_interface_class_id": 122,
  "likely_interface_class_name": "Key Expiration Control Function",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "44 function control",
    "D": "1 key expiration control",
    "E": "0",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Key expiration control function at 0-0:44.1.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about enabling/disabling the key check (key expiration) function.",
    "ABNT Appendix 9 describes this object as controlling enabling/disabling of the key check function."
  ]
}
```

## Notes
