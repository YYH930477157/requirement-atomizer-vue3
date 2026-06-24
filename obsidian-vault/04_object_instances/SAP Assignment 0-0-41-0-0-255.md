---
id: KB-OBIS-0-0-41-0-0-255-SAP-ASSIGNMENT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: SAP Assignment
aliases:
- SAP Assignment 0-0:41.0.0.255
- SAP assignment list object
keywords:
- 0-0:41.0.0.255
- SAP Assignment
- SAP_assignment_list
- logical device SAP list
domain_tags:
- cosem_object
- association
- logical_device
relations:
- relation: instance_of
  target: KB-L3-IC-17-SAP-ASSIGNMENT
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# SAP Assignment

## Definition

Row-level COSEM object instance for the SAP Assignment logical name `0-0:41.0.0.255`, used to expose the SAP assignment list for logical devices.

## Aliases

- SAP Assignment 0-0:41.0.0.255
- SAP assignment list object

## Domain Tags

- `cosem_object`
- `association`
- `logical_device`

## Relations

- `instance_of` -> `KB-L3-IC-17-SAP-ASSIGNMENT`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:41.0.0.255",
  "likely_interface_class_id": 17,
  "likely_interface_class_name": "SAP Assignment",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "41 SAP assignment",
    "D": "0 default instance",
    "E": "0 default instance",
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
      "section": "Table 22 SAP assignment, LN association and security objects"
    }
  ],
  "applicable_notes": [
    "ABNT Appendix 9 uses this object with class_id 17 and value 0-0:41.0.0.255.",
    "Use as the row-level object anchor for SAP_assignment_list access-right requirements."
  ]
}
```

## Notes
