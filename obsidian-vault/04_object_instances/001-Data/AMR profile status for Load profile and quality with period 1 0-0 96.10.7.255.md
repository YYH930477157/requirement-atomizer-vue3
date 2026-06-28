---
id: KB-ABNT-OBIS-0-0-96-10-7-255-AMR-PROFILE-STATUS-FOR-LOAD-PROFILE-AND-QUALITY-WITH-PERIOD-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: AMR profile status for Load profile and quality with period 1
aliases:
- OBIS 0-0:96.10.7.255
keywords:
- 0-0:96.10.7.255
- AMR profile status for Load profile and quality with period 1
- TBL-000105
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

# AMR profile status for Load profile and quality with period 1

## Definition

Row-level Data object at logical name `0-0:96.10.7.255`. AMR profile status for load profile and quality, period 1

## Aliases

- OBIS 0-0:96.10.7.255

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
  "obis_pattern": "0-0:96.10.7.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "96 abstract general data objects",
    "D": "10 status",
    "E": "7 AMR profile status (load profile, period 1)",
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
      "section": "AMR profile status for Load profile and quality with period 1 at 0-0:96.10.7.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about amr profile status for load profile and quality.",
    "ABNT Appendix 9 describes this object as: AMR profile status for load profile and quality, period 1."
  ]
}
```

## Notes
