---
id: KB-ABNT-OBIS-0-0-96-10-1-255-INSTANTANEOUS-PHASE-SEQUENCE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous phase sequence
aliases:
- OBIS 0-0:96.10.1.255
keywords:
- 0-0:96.10.1.255
- Instantaneous phase sequence
- TBL-000125
domain_tags:
- cosem_object
- general
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Instantaneous phase sequence

## Definition

Row-level Data object at logical name `0-0:96.10.1.255`. Instantaneous phase sequence

## Aliases

- OBIS 0-0:96.10.1.255

## Domain Tags

- `cosem_object`
- `general`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.10.1.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "96 abstract general data objects",
    "D": "10 status/phase",
    "E": "1 phase sequence",
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
      "section": "Instantaneous phase sequence at 0-0:96.10.1.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about instantaneous phase sequence.",
    "ABNT Appendix 9 describes this object as: instantaneous phase sequence."
  ]
}
```

## Notes
