---
id: KB-OBIS-8-B-0-8-4-VZ-WATER-RECORDING-INTERVAL-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Water recording interval 1
aliases:
- Cold water recording interval
- OBIS 8-b:0.8.4.VZ
keywords:
- 8-b:0.8.4.VZ
- water recording interval 1
- cold water recording interval
- water service entry object
domain_tags:
- cosem_object
- water
- recording_interval
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-68
---

# Water recording interval 1

## Definition

Pattern-level row entry for water recording interval 1, represented by OBIS pattern `8-b:0.8.4.VZ`.

## Aliases

- Cold water recording interval
- OBIS 8-b:0.8.4.VZ

## Domain Tags

- `cosem_object`
- `water`
- `recording_interval`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-68`

## Structured Data

```json metadata
{
  "obis_pattern": "8-b:0.8.4.VZ",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "water",
  "value_group_mapping": {
    "A": "8 cold water",
    "B": "b channel selector",
    "C": "0 general purpose objects",
    "D": "8 measurement period / recording interval / billing period duration",
    "E": "4 recording interval 1",
    "F": "VZ billing-period selector where applicable"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 68,
    "title": "OBIS codes for general and service entry objects - Water"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 68 general and service entry objects - Water"
    }
  ],
  "applicable_notes": [
    "Use this pattern for cold-water profile recording-period parameters.",
    "The VZ value identifies billing-period allocation when historical values are relevant."
  ]
}
```

## Notes

