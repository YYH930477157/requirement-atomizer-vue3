---
id: KB-OBIS-1-1-91-7-0-255-INSTANTANEOUS-NEUTRAL-CURRENT-CALCULATED
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous neutral current (calculated)
aliases:
- Calculated neutral current instantaneous
- Instantaneous neutral current calculated
- OBIS 1-1:91.7.0.255
keywords:
- 1-1:91.7.0.255
- Instantaneous neutral current (calculated)
- calculated neutral current
- neutral current calculated
- instantaneous neutral current calculated
domain_tags:
- cosem_object
- ac_electricity
- current
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Instantaneous neutral current (calculated)

## Definition

Row-level OBIS object for AC electricity calculated instantaneous neutral current, represented by logical name pattern `1-1:91.7.0.255`.

## Aliases

- Calculated neutral current instantaneous
- Instantaneous neutral current calculated
- OBIS 1-1:91.7.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `current`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-1:91.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "1 channel 1 / calculated variant",
    "C": "91 neutral current",
    "D": "7 instantaneous value",
    "E": "0 total/default",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 13,
    "title": "Value group C codes - AC Electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 13 AC electricity C=91 neutral current; Table 14 D=7 instantaneous value"
    },
    {
      "source": "ABNT Appendix 9 extracted table TBL-000112",
      "section": "TBL-000112-R000010 Instantaneous neutral current (calculated)"
    }
  ],
  "applicable_notes": [
    "C=91 identifies neutral current in the AC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value.",
    "ABNT Appendix 9 distinguishes this calculated neutral current from the measured neutral current at B=0."
  ]
}
```

## Notes

