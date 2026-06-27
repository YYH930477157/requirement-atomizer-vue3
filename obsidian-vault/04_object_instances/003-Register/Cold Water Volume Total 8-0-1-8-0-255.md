---
id: KB-OBIS-8-0-1-8-0-255-WATER-VOLUME-TOTAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Cold water volume total
aliases:
- Water volume total
- Cold water consumption total
- OBIS 8-0:1.8.0.255
keywords:
- 8-0:1.8.0.255
- cold water volume total
- water volume total
- cold water consumption
domain_tags:
- cosem_object
- water
- volume
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-65
---

# Cold water volume total

## Definition

Row-level OBIS object for cold water volume total, represented by logical name pattern `8-0:1.8.0.255`.

## Aliases

- Water volume total
- Cold water consumption total
- OBIS 8-0:1.8.0.255

## Domain Tags

- `cosem_object`
- `water`
- `volume`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-65`

## Structured Data

```json metadata
{
  "obis_pattern": "8-0:1.8.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "water",
  "value_group_mapping": {
    "A": "8 cold water",
    "B": "0 no channel",
    "C": "1 water volume",
    "D": "8 time integral 1",
    "E": "0 total",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 65,
    "title": "Value group C codes - Water"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 65 water C=1 volume"
    }
  ],
  "applicable_notes": [
    "A=8 identifies cold water in the OBIS medium group.",
    "C=1 identifies volume; D=8 is used for time-integral quantities."
  ]
}
```

## Notes

