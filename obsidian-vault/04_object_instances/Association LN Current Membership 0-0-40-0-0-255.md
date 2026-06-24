---
id: KB-OBIS-0-0-40-0-0-255-ASSOCIATION-LN-CURRENT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Association LN - current membership
aliases:
- Association LN 0-0:40.0.0.255
- Current membership association
keywords:
- 0-0:40.0.0.255
- Association LN current membership
- current membership association
- object_list association
domain_tags:
- cosem_object
- association
- security_policy
relations:
- relation: instance_of
  target: KB-L3-IC-15-ASSOCIATION-LN
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Association LN - current membership

## Definition

Row-level COSEM object instance for the current Association LN logical name `0-0:40.0.0.255`, used to describe the active logical-name association and its object list.

## Aliases

- Association LN 0-0:40.0.0.255
- Current membership association

## Domain Tags

- `cosem_object`
- `association`
- `security_policy`

## Relations

- `instance_of` -> `KB-L3-IC-15-ASSOCIATION-LN`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:40.0.0.255",
  "likely_interface_class_id": 15,
  "likely_interface_class_name": "Association LN",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "40 Association LN",
    "D": "0 current membership",
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
      "section": "Table 22 Association LN current membership row"
    }
  ],
  "applicable_notes": [
    "ABNT Appendix 9 labels this instance as Current membership.",
    "Use this row when matching association object_list and xDLMS context requirements for the current association."
  ]
}
```

## Notes
