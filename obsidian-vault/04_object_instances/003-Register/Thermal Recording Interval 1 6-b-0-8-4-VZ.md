---
id: KB-OBIS-6-B-0-8-4-VZ-THERMAL-RECORDING-INTERVAL-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Thermal recording interval 1
aliases:
- Thermal energy recording interval
- OBIS 6-b:0.8.4.VZ
keywords:
- 6-b:0.8.4.VZ
- thermal recording interval 1
- thermal energy recording interval
- thermal service entry object
domain_tags:
- cosem_object
- thermal_energy
- recording_interval
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-45
---

# Thermal recording interval 1

## Definition

Pattern-level row entry for thermal energy recording interval 1, represented by OBIS pattern `6-b:0.8.4.VZ`.

## Aliases

- Thermal energy recording interval
- OBIS 6-b:0.8.4.VZ

## Domain Tags

- `cosem_object`
- `thermal_energy`
- `recording_interval`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-45`

## Structured Data

```json metadata
{
  "obis_pattern": "6-b:0.8.4.VZ",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "thermal_energy",
  "value_group_mapping": {
    "A": "6 thermal energy",
    "B": "b channel selector",
    "C": "0 general purpose objects",
    "D": "8 measurement period / recording interval / billing period duration",
    "E": "4 recording interval 1",
    "F": "VZ billing-period selector where applicable"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 45,
    "title": "OBIS codes for general and service entry objects - Thermal energy"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 45 general and service entry objects - Thermal energy"
    }
  ],
  "applicable_notes": [
    "Use this pattern for thermal profile recording-period parameters.",
    "The VZ value identifies billing-period allocation when historical values are relevant."
  ]
}
```

## Notes

