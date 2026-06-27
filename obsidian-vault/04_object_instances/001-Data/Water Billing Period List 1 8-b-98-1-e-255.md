---
id: KB-OBIS-8-B-98-1-E-255-WATER-BILLING-LIST-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Water billing period list 1
aliases:
- Cold water billing list 1
- Water billing period list 1
- OBIS 8-b:98.1.e.255
keywords:
- 8-b:98.1.e.255
- water billing period list 1
- cold water billing list
- water list object
domain_tags:
- cosem_object
- water
- billing
- list_object
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-70
---

# Water billing period list 1

## Definition

Pattern-level row entry for water billing period list objects, represented by OBIS pattern `8-b:98.1.e.255`.

## Aliases

- Cold water billing list 1
- Water billing period list 1
- OBIS 8-b:98.1.e.255

## Domain Tags

- `cosem_object`
- `water`
- `billing`
- `list_object`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-70`

## Structured Data

```json metadata
{
  "obis_pattern": "8-b:98.1.e.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "water",
  "value_group_mapping": {
    "A": "8 cold water",
    "B": "b channel selector",
    "C": "98 list objects",
    "D": "1 billing period list 1",
    "E": "e list selector",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 70,
    "title": "OBIS codes for list objects - Water"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 70 list objects - Water"
    }
  ],
  "applicable_notes": [
    "Use this pattern for water list objects that hold billing-period data.",
    "The B and E groups select the concrete channel and list variant."
  ]
}
```

## Notes

