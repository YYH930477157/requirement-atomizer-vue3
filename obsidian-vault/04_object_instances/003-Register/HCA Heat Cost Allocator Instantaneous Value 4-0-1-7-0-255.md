---
id: KB-OBIS-4-0-1-7-0-255-HCA-HEAT-COST-ALLOCATOR-INSTANTANEOUS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: HCA heat cost allocator instantaneous value
aliases:
- Heat cost allocator instantaneous value
- HCA instantaneous value
- OBIS 4-0:1.7.0.255
keywords:
- 4-0:1.7.0.255
- hca heat cost allocator instantaneous value
- heat cost allocator instantaneous value
- hca instantaneous value
domain_tags:
- cosem_object
- hca
- heat_cost_allocator
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-41
---

# HCA heat cost allocator instantaneous value

## Definition

Pattern-level OBIS object for a heat cost allocator instantaneous value, represented by logical name pattern `4-0:1.7.0.255`.

## Aliases

- Heat cost allocator instantaneous value
- HCA instantaneous value
- OBIS 4-0:1.7.0.255

## Domain Tags

- `cosem_object`
- `hca`
- `heat_cost_allocator`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-41`

## Structured Data

```json metadata
{
  "obis_pattern": "4-0:1.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "hca",
  "value_group_mapping": {
    "A": "4 heat cost allocator",
    "B": "0 no channel",
    "C": "1 heat cost allocator value",
    "D": "7 instantaneous value",
    "E": "0 total or default selector",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 41,
    "title": "OBIS codes for HCA related objects (examples)"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 41 HCA related objects examples"
    }
  ],
  "applicable_notes": [
    "Pattern-level representative for HCA related object examples.",
    "D=7 identifies an instantaneous value in the HCA example object family."
  ]
}
```

## Notes

