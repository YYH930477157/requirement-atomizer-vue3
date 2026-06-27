---
id: KB-OBIS-4-B-0-8-4-VZ-HCA-RECORDING-INTERVAL-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: HCA recording interval 1
aliases:
- HCA recording interval
- Heat cost allocator recording interval 1
- OBIS 4-b:0.8.4.VZ
keywords:
- 4-b:0.8.4.VZ
- HCA recording interval 1
- heat cost allocator recording interval
- HCA service entry object
domain_tags:
- cosem_object
- hca
- heat_cost_allocator
- recording_interval
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-37
---

# HCA recording interval 1

## Definition

Pattern-level row entry for heat cost allocator recording interval 1, represented by OBIS pattern `4-b:0.8.4.VZ`.

## Aliases

- HCA recording interval
- Heat cost allocator recording interval 1
- OBIS 4-b:0.8.4.VZ

## Domain Tags

- `cosem_object`
- `hca`
- `heat_cost_allocator`
- `recording_interval`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-37`

## Structured Data

```json metadata
{
  "obis_pattern": "4-b:0.8.4.VZ",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "hca",
  "value_group_mapping": {
    "A": "4 heat cost allocator",
    "B": "b channel selector",
    "C": "0 general purpose objects",
    "D": "8 measurement period / recording interval / billing period duration",
    "E": "4 recording interval 1",
    "F": "VZ billing-period selector where applicable"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 37,
    "title": "OBIS codes for general and service entry objects - HCA"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 37 general and service entry objects - HCA"
    }
  ],
  "applicable_notes": [
    "Use this pattern for HCA recording-period parameters.",
    "The B and VZ groups select the concrete channel and billing-period allocation."
  ]
}
```

## Notes

