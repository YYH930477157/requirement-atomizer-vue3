---
id: KB-OBIS-8-0-5-4-0-255-WATER-TEMPERATURE-AVERAGE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Cold water temperature average
aliases:
- Water temperature average
- Cold water average temperature
- OBIS 8-0:5.4.0.255
keywords:
- 8-0:5.4.0.255
- cold water temperature average
- average water temperature
- water average temperature
domain_tags:
- cosem_object
- water
- temperature
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-65
---

# Cold water temperature average

## Definition

Row-level OBIS object for cold water average temperature, represented by logical name pattern `8-0:5.4.0.255`.

## Aliases

- Water temperature average
- Cold water average temperature
- OBIS 8-0:5.4.0.255

## Domain Tags

- `cosem_object`
- `water`
- `temperature`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-65`

## Structured Data

```json metadata
{
  "obis_pattern": "8-0:5.4.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "water",
  "value_group_mapping": {
    "A": "8 cold water",
    "B": "0 no channel",
    "C": "5 temperature",
    "D": "4 average value",
    "E": "0 total/default",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 65,
    "title": "Value group C codes - Water"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 65 water C=5 temperature"
    }
  ],
  "applicable_notes": [
    "A=8 identifies cold water in the OBIS medium group.",
    "C=5 identifies temperature; D=4 identifies an average measurement value."
  ]
}
```

## Notes

