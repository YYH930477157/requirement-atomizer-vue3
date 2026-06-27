---
id: KB-OBIS-7-B-0-8-4-VZ-GAS-RECORDING-INTERVAL-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas recording interval 1
aliases:
- Gas recording interval
- OBIS 7-b:0.8.4.VZ
keywords:
- 7-b:0.8.4.VZ
- gas recording interval 1
- gas service entry object
- recording interval gas
domain_tags:
- cosem_object
- gas
- recording_interval
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-61
---

# Gas recording interval 1

## Definition

Pattern-level row entry for gas recording interval 1, represented by OBIS pattern `7-b:0.8.4.VZ`.

## Aliases

- Gas recording interval
- OBIS 7-b:0.8.4.VZ

## Domain Tags

- `cosem_object`
- `gas`
- `recording_interval`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-61`

## Structured Data

```json metadata
{
  "obis_pattern": "7-b:0.8.4.VZ",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "b channel selector",
    "C": "0 general purpose objects",
    "D": "8 measurement period / recording interval / billing period duration",
    "E": "4 recording interval 1",
    "F": "VZ billing-period selector where applicable"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 61,
    "title": "OBIS codes for general and service entry objects - Gas"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 61 general and service entry objects - Gas"
    }
  ],
  "applicable_notes": [
    "Use this pattern for gas profile recording-period parameters.",
    "The VZ value identifies billing-period allocation when historical values are relevant."
  ]
}
```

## Notes

