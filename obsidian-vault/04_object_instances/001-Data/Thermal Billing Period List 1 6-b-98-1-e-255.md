---
id: KB-OBIS-6-B-98-1-E-255-THERMAL-BILLING-LIST-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Thermal billing period list 1
aliases:
- Thermal billing list 1
- Thermal energy billing period list 1
- OBIS 6-b:98.1.e.255
keywords:
- 6-b:98.1.e.255
- thermal billing period list 1
- thermal energy billing list
- thermal list object
domain_tags:
- cosem_object
- thermal_energy
- billing
- list_object
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-47
---

# Thermal billing period list 1

## Definition

Pattern-level row entry for thermal energy billing period list objects, represented by OBIS pattern `6-b:98.1.e.255`.

## Aliases

- Thermal billing list 1
- Thermal energy billing period list 1
- OBIS 6-b:98.1.e.255

## Domain Tags

- `cosem_object`
- `thermal_energy`
- `billing`
- `list_object`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-47`

## Structured Data

```json metadata
{
  "obis_pattern": "6-b:98.1.e.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "thermal_energy",
  "value_group_mapping": {
    "A": "6 thermal energy",
    "B": "b channel selector",
    "C": "98 list objects",
    "D": "1 billing period list 1",
    "E": "e list selector",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 47,
    "title": "OBIS codes for list objects - Thermal energy"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 47 list objects - Thermal energy"
    }
  ],
  "applicable_notes": [
    "Use this pattern for thermal list objects that hold billing-period data.",
    "The B and E groups select the concrete channel and list variant."
  ]
}
```

## Notes

