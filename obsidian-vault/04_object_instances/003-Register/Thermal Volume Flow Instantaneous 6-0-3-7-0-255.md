---
id: KB-OBIS-6-0-3-7-0-255-VOLUME-FLOW-INSTANTANEOUS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Thermal volume flow instantaneous
aliases:
- Volume flow instantaneous thermal energy
- Thermal volume flow
- OBIS 6-0:3.7.0.255
keywords:
- 6-0:3.7.0.255
- thermal volume flow instantaneous
- volume flow
- thermal energy flow
domain_tags:
- cosem_object
- thermal_energy
- flow
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-42
---

# Thermal volume flow instantaneous

## Definition

Row-level OBIS object for thermal energy instantaneous volume flow, represented by logical name pattern `6-0:3.7.0.255`.

## Aliases

- Volume flow instantaneous thermal energy
- Thermal volume flow
- OBIS 6-0:3.7.0.255

## Domain Tags

- `cosem_object`
- `thermal_energy`
- `flow`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-42`

## Structured Data

```json metadata
{
  "obis_pattern": "6-0:3.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "thermal_energy",
  "value_group_mapping": {
    "A": "6 thermal energy",
    "B": "0 no channel",
    "C": "3 volume flow",
    "D": "7 instantaneous value",
    "E": "0 total/default",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 42,
    "title": "Value group C codes - Thermal energy"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 42 thermal energy C=3 volume flow"
    }
  ],
  "applicable_notes": [
    "C=3 identifies volume flow in the thermal-energy C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

