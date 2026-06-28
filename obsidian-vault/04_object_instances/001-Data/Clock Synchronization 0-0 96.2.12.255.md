---
id: KB-ABNT-OBIS-0-0-96-2-12-255-CLOCK-SYNCHRONIZATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Clock Synchronization
aliases:
- OBIS 0-0:96.2.12.255
keywords:
- 0-0:96.2.12.255
- Clock Synchronization
- TBL-000043
domain_tags:
- cosem_object
- general
- general
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Clock Synchronization

## Definition

Row-level Data object at logical name `0-0:96.2.12.255`. Clock synchronization status

## Aliases

- OBIS 0-0:96.2.12.255

## Domain Tags

- `cosem_object`
- `general`
- `general`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.2.12.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "96 abstract general data objects",
    "D": "2 configuration",
    "E": "12 clock synchronization",
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
      "section": "Table 8 OBIS codes for general and service entry objects"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Clock Synchronization at 0-0:96.2.12.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about clock synchronization status.",
    "ABNT Appendix 9 describes this object as: clock synchronization status."
  ]
}
```

## Notes
