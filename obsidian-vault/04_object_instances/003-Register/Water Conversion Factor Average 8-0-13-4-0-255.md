---
id: KB-OBIS-8-0-13-4-0-255-WATER-CONVERSION-FACTOR-AVERAGE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Water conversion factor average
aliases:
- Average water conversion factor
- Water measurement conversion factor average
- OBIS 8-0:13.4.0.255
keywords:
- 8-0:13.4.0.255
- water conversion factor average
- average water conversion factor
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

# Water conversion factor average

## Definition

Pattern-level OBIS object for an average water related conversion factor, represented by logical name pattern `8-0:13.4.0.255`.

## Aliases

- Average water conversion factor
- Water measurement conversion factor average
- OBIS 8-0:13.4.0.255

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
  "obis_pattern": "8-0:13.4.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "water",
  "value_group_mapping": {
    "A": "8 water",
    "B": "0 no channel",
    "C": "13 water conversion factor",
    "D": "4 average value",
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
    "Pattern-level representative for an average water related conversion factor.",
    "Use water C/D/E value-group tables to resolve the exact conversion quantity and averaging semantics."
  ]
}
```

## Notes
