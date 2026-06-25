---
id: KB-OBIS-1-B-0-8-4-VZ-AC-RECORDING-INTERVAL-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: AC recording interval 1
aliases:
- Recording interval 1 AC
- AC load profile recording interval
keywords:
- 1-b:0.8.4.VZ
- AC recording interval 1
- recording interval 1 AC
- load profile recording interval AC
domain_tags:
- cosem_object
- ac_electricity
- load_profile
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-21
---

# AC recording interval 1

## Definition

Pattern-level row entry for AC electricity recording interval 1, represented by OBIS pattern `1-b:0.8.4.VZ`.

## Aliases

- Recording interval 1 AC
- AC load profile recording interval

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `load_profile`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-21`

## Structured Data

```json metadata
{
  "obis_pattern": "1-b:0.8.4.VZ",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "b channel selector",
    "C": "0 general purpose objects",
    "D": "8 measurement period / recording interval / billing period duration",
    "E": "4 recording interval 1 for load profile",
    "F": "VZ billing-period selector where applicable"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 21,
    "title": "OBIS codes for general and service entry objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 21 general and service entry objects - AC electricity"
    }
  ],
  "applicable_notes": [
    "This row parameterizes load profile recording period 1 for AC electricity.",
    "The VZ value identifies billing-period allocation when historical values are relevant."
  ]
}
```

## Notes

