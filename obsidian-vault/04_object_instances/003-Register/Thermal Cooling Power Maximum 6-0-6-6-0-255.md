---
id: KB-OBIS-6-0-6-6-0-255-THERMAL-COOLING-POWER-MAXIMUM
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Thermal cooling power maximum
aliases:
- Cooling power maximum
- Thermal cooling maximum power
- OBIS 6-0:6.6.0.255
keywords:
- 6-0:6.6.0.255
- thermal cooling power maximum
- cooling power maximum
- maximum cooling power
domain_tags:
- cosem_object
- thermal_energy
- cooling_energy
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-49
---

# Thermal cooling power maximum

## Definition

Pattern-level OBIS object for thermal-energy related maximum cooling power, represented by logical name pattern `6-0:6.6.0.255`.

## Aliases

- Cooling power maximum
- Thermal cooling maximum power
- OBIS 6-0:6.6.0.255

## Domain Tags

- `cosem_object`
- `thermal_energy`
- `cooling_energy`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-49`

## Structured Data

```json metadata
{
  "obis_pattern": "6-0:6.6.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "thermal_energy",
  "value_group_mapping": {
    "A": "6 thermal energy",
    "B": "0 no channel",
    "C": "6 cooling energy",
    "D": "6 maximum value",
    "E": "0 total or default selector",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 49,
    "title": "OBIS codes for Thermal energy related objects (examples)"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 49 thermal energy related objects examples"
    }
  ],
  "applicable_notes": [
    "Pattern-level representative for thermal-energy related object examples.",
    "D=6 identifies a maximum value in the thermal cooling example object family."
  ]
}
```

## Notes

