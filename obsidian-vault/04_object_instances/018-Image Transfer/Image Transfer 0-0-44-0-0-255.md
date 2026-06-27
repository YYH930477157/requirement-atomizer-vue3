---
id: KB-OBIS-0-0-44-0-0-255-IMAGE-TRANSFER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Image Transfer
aliases:
- Image Transfer 0-0:44.0.0.255
- Firmware Image Transfer
keywords:
- 0-0:44.0.0.255
- Image Transfer
- firmware image transfer
- image transfer object
domain_tags:
- cosem_object
- firmware
- image_transfer
- data_model
relations:
- relation: instance_of
  target: KB-L3-IC-18-IMAGE-TRANSFER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Image Transfer

## Definition

Row-level Image Transfer object for firmware or image delivery at logical name `0-0:44.0.0.255`.

## Aliases

- Image Transfer 0-0:44.0.0.255
- Firmware Image Transfer

## Domain Tags

- `cosem_object`
- `firmware`
- `image_transfer`
- `data_model`

## Relations

- `instance_of` -> `KB-L3-IC-18-IMAGE-TRANSFER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:44.0.0.255",
  "likely_interface_class_id": 18,
  "likely_interface_class_name": "Image Transfer",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "44 Image Transfer",
    "D": "0 default image transfer instance",
    "E": "0 default image transfer object",
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
      "section": "Image Transfer interface class"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Image Transfer at 0-0:44.0.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching firmware or COSEM image transfer requirements.",
    "ABNT Appendix 9 uses this instance for transferring firmware images to the COSEM server before activation."
  ]
}
```

## Notes
