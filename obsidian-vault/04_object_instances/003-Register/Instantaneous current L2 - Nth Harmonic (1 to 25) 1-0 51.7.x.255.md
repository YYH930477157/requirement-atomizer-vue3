---
id: KB-ABNT-OBIS-1-0-51-7-X-255-INSTANTANEOUS-CURRENT-L2-NTH-HARMONIC-1-TO-25
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous current L2 - Nth Harmonic (1 to 25)
aliases:
- OBIS 1-0:51.7.x.255
keywords:
- 1-0:51.7.x.255
- Instantaneous current L2 - Nth Harmonic (1 to 25)
- TBL-000110
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-16
---

# Instantaneous current L2 - Nth Harmonic (1 to 25)

## Definition

Row-level Register object at logical name `1-0:51.7.x.255`. Instantaneous current L2 - Nth Harmonic (1 to 25).

## Aliases

- OBIS 1-0:51.7.x.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-16`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:51.7.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "51 current phase L2",
    "D": "7 instantaneous/Nth harmonic",
    "E": "x tariff/rate index (templated)",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 16,
    "title": "Value group E codes - AC electricity - Harmonics"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 16 Value group E codes - AC electricity - Harmonics"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Instantaneous current L2 - Nth Harmonic (1 to 25) at 1-0:51.7.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about instantaneous current l2 - nth harmonic (1 to 25).",
    "ABNT Appendix 9 describes this object as: Instantaneous current L2 - Nth Harmonic (1 to 25)."
  ]
}
```

## Notes
