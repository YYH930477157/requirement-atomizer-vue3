---
id: KB-OBIS-0-B-96-1-0-DEVICE-ID-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Device ID 1
aliases:
- Device ID 1 0-b:96.1.0
- Meter device identifier 1
keywords:
- 0-b:96.1.0
- Device ID 1
- device identifier 1
- meter device identifier 1
domain_tags:
- cosem_object
- identification
- device_identity
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Device ID 1

## Definition

Row-level OBIS object for the first device identifier data value, represented by logical name pattern `0-b:96.1.0`.

## Aliases

- Device ID 1 0-b:96.1.0
- Meter device identifier 1

## Domain Tags

- `cosem_object`
- `identification`
- `device_identity`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-b:96.1.0",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "b logical-device or channel selector",
    "C": "96 identification objects",
    "D": "1 device ID group",
    "E": "0 device ID 1"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects: device ID #1 0-b:96.1.0"
    }
  ],
  "applicable_notes": [
    "Use this row when a requirement refers to the first device identifier rather than a generic identification object.",
    "The object is represented as Data class in the row-level knowledge base."
  ]
}
```

## Notes

