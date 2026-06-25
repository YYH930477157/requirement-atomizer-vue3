---
id: KB-OBIS-2-B-0-8-4-VZ-DC-RECORDING-INTERVAL-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC recording interval 1
aliases:
- Recording interval 1 DC
- DC load profile recording interval
keywords:
- 2-b:0.8.4.VZ
- DC recording interval 1
- recording interval 1 DC
- load profile recording interval DC
domain_tags:
- cosem_object
- dc_electricity
- load_profile
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-29
---

# DC recording interval 1

## Definition

Pattern-level row entry for DC electricity recording interval 1, represented by OBIS pattern `2-b:0.8.4.VZ`.

## Aliases

- Recording interval 1 DC
- DC load profile recording interval

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `load_profile`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-29`

## Structured Data

```json metadata
{
  "obis_pattern": "2-b:0.8.4.VZ",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "b channel selector",
    "C": "0 general purpose objects",
    "D": "8 measurement period / recording interval / billing period duration",
    "E": "4 recording interval 1 for load profile",
    "F": "VZ billing-period selector where applicable"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 29,
    "title": "OBIS codes for general and service entry objects - DC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 29 general and service entry objects - DC electricity"
    }
  ],
  "applicable_notes": [
    "This row parameterizes load profile recording period 1 for DC electricity.",
    "The VZ value identifies billing-period allocation when historical values are relevant."
  ]
}
```

## Notes

