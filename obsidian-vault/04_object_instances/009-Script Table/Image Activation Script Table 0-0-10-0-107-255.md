---
id: KB-OBIS-0-0-10-0-107-255-IMAGE-ACTIVATION-SCRIPT-TABLE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Predefined Scripts - Image Activation
aliases:
- Image activation script table 0-0:10.0.107.255
- Firmware image activation script
keywords:
- 0-0:10.0.107.255
- Predefined Scripts - Image Activation
- image activation script
- firmware activation script
domain_tags:
- cosem_object
- script
- firmware
- image_transfer
relations:
- relation: instance_of
  target: KB-L3-IC-9-SCRIPT-TABLE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Predefined Scripts - Image Activation

## Definition

Row-level Script Table object for firmware image activation actions at logical name `0-0:10.0.107.255`.

## Aliases

- Image activation script table 0-0:10.0.107.255
- Firmware image activation script

## Domain Tags

- `cosem_object`
- `script`
- `firmware`
- `image_transfer`

## Relations

- `instance_of` -> `KB-L3-IC-9-SCRIPT-TABLE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:10.0.107.255",
  "likely_interface_class_id": 9,
  "likely_interface_class_name": "Script Table",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "10 Script Table",
    "D": "0 predefined script group",
    "E": "107 image activation script",
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
      "source": "Blue Book Part 2 Ed. 16",
      "section": "Script Table interface class"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Predefined Scripts - Image Activation at 0-0:10.0.107.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching firmware image activation scripts.",
    "Image Activation Scheduler objects can execute scripts from this table after Image Transfer completes."
  ]
}
```

## Notes
