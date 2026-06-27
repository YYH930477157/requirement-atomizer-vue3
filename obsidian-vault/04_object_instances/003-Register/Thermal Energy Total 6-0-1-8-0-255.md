---
id: KB-OBIS-6-0-1-8-0-255-THERMAL-ENERGY-TOTAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Thermal energy total
aliases:
- Heat energy total
- Thermal energy time integral 1 total
- OBIS 6-0:1.8.0.255
keywords:
- 6-0:1.8.0.255
- thermal energy total
- heat energy total
- thermal energy time integral
domain_tags:
- cosem_object
- thermal_energy
- energy
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-42
---

# Thermal energy total

## Definition

Row-level OBIS object for thermal energy total, represented by logical name pattern `6-0:1.8.0.255`.

## Aliases

- Heat energy total
- Thermal energy time integral 1 total
- OBIS 6-0:1.8.0.255

## Domain Tags

- `cosem_object`
- `thermal_energy`
- `energy`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-42`

## Structured Data

```json metadata
{
  "obis_pattern": "6-0:1.8.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "thermal_energy",
  "value_group_mapping": {
    "A": "6 thermal energy",
    "B": "0 no channel",
    "C": "1 thermal energy",
    "D": "8 time integral 1",
    "E": "0 total",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 42,
    "title": "Value group C codes - Thermal energy"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 42 thermal energy C=1 energy"
    }
  ],
  "applicable_notes": [
    "C=1 identifies thermal energy in the thermal-energy C-code family.",
    "D=8 is used for time-integral energy quantities; E=0 identifies total."
  ]
}
```

## Notes

