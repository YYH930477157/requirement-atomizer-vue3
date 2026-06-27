---
id: KB-OBIS-6-B-97-97-E-THERMAL-ERROR-REGISTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Thermal error register
aliases:
- Thermal error register 6-b:97.97.e
- Thermal energy error register
keywords:
- 6-b:97.97.e
- thermal error register
- thermal energy error register
- error register thermal
domain_tags:
- cosem_object
- thermal_energy
- error
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-46
---

# Thermal error register

## Definition

Pattern-level row entry for thermal energy error register objects using OBIS pattern `6-b:97.97.e`.

## Aliases

- Thermal error register 6-b:97.97.e
- Thermal energy error register

## Domain Tags

- `cosem_object`
- `thermal_energy`
- `error`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-46`

## Structured Data

```json metadata
{
  "obis_pattern": "6-b:97.97.e",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "thermal_energy",
  "value_group_mapping": {
    "A": "6 thermal energy",
    "B": "b channel selector",
    "C": "97 error register objects",
    "D": "97 error register",
    "E": "e error register selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 46,
    "title": "OBIS codes for error register objects - Thermal energy"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 46 error register objects - Thermal energy"
    }
  ],
  "applicable_notes": [
    "The Blue Book table identifies the thermal error-register object family.",
    "Concrete bit assignments remain project/profile specific."
  ]
}
```

## Notes

