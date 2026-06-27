---
id: KB-OBIS-8-0-13-6-0-255-WATER-CONVERSION-FACTOR-MAXIMUM
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Water conversion factor maximum
aliases:
- Maximum water conversion factor
- Water measurement conversion factor maximum
- OBIS 8-0:13.6.0.255
keywords:
- 8-0:13.6.0.255
- water conversion factor maximum
- maximum water conversion factor
- water related object
domain_tags:
- cosem_object
- water
- conversion
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-72
---

# Water conversion factor maximum

## Definition

Pattern-level OBIS object for a maximum water related conversion factor, represented by logical name pattern `8-0:13.6.0.255`.

## Aliases

- Maximum water conversion factor
- Water measurement conversion factor maximum
- OBIS 8-0:13.6.0.255

## Domain Tags

- `cosem_object`
- `water`
- `conversion`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-72`

## Structured Data

```json metadata
{
  "obis_pattern": "8-0:13.6.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "water",
  "value_group_mapping": {
    "A": "8 water",
    "B": "0 no channel",
    "C": "13 water conversion factor",
    "D": "6 maximum value",
    "E": "0 total or default selector",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 72,
    "title": "OBIS codes for water related objects (examples)"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 72 water related objects examples"
    }
  ],
  "applicable_notes": [
    "Pattern-level representative for a maximum water related conversion factor.",
    "Use water C/D/E value-group tables to resolve the exact conversion quantity and maximum-value semantics."
  ]
}
```

## Notes
