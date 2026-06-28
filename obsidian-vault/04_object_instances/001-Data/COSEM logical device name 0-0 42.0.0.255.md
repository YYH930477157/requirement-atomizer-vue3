---
id: KB-ABNT-OBIS-0-0-42-0-0-255-COSEM-LOGICAL-DEVICE-NAME
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: COSEM logical device name
aliases:
- OBIS 0-0:42.0.0.255
keywords:
- 0-0:42.0.0.255
- COSEM logical device name
- cosem logical device name
- TBL-000042
domain_tags:
- cosem_object
- general
- data_model
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# COSEM logical device name

## Definition

Row-level Data object holding the COSEM logical device name (LDN) at logical name `0-0:42.0.0.255`.

## Aliases

- OBIS 0-0:42.0.0.255

## Domain Tags

- `cosem_object`
- `general`
- `data_model`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:42.0.0.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "42 COSEM logical device name",
    "D": "0",
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
      "section": "COSEM logical device name at 0-0:42.0.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements that identify a physical/logical meter device by its COSEM logical device name.",
    "ABNT Appendix 9 registers this object as the COSEM logical device name (LDN), the standard Data object identifying the logical device."
  ]
}
```

## Notes
