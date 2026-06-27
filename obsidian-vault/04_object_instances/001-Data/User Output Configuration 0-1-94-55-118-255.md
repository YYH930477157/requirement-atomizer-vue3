---
id: KB-OBIS-0-1-94-55-118-255-USER-OUTPUT-CONFIGURATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: User output configuration
aliases:
- User output configuration 0-1:94.55.118.255
- User Exit Configuration
keywords:
- 0-1:94.55.118.255
- User output configuration
- User Exit Configuration
- output configuration
domain_tags:
- cosem_object
- data_model
- output_control
- configuration
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# User output configuration

## Definition

Row-level Data object for user output configuration at logical name `0-1:94.55.118.255`.

## Aliases

- User output configuration 0-1:94.55.118.255
- User Exit Configuration

## Domain Tags

- `cosem_object`
- `data_model`
- `output_control`
- `configuration`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-1:94.55.118.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 utility-specific channel",
    "C": "94 utility-specific data objects",
    "D": "55 configuration group",
    "E": "118 user output configuration",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 9,
    "title": "OBIS codes for data objects - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 9 data objects - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "User output configuration at 0-1:94.55.118.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching user-output or user-exit configuration requirements.",
    "ABNT Appendix 9 labels this object as User Exit Configuration."
  ]
}
```

## Notes
