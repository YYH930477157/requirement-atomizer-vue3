---
id: KB-OBIS-1-0-91-7-0-255-INSTANTANEOUS-NEUTRAL-CURRENT-MEASURED
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous neutral current (measured)
aliases:
- Instantaneous Neutral current
- Measured neutral current instantaneous
- OBIS 1-0:91.7.0.255
keywords:
- 1-0:91.7.0.255
- Instantaneous neutral current (measured)
- instantaneous neutral current
- measured neutral current
- neutral current measured
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

# Instantaneous neutral current (measured)

## Definition

Row-level OBIS object for AC electricity measured instantaneous neutral current, represented by logical name pattern `1-0:91.7.0.255`.

## Aliases

- Instantaneous Neutral current
- Measured neutral current instantaneous
- OBIS 1-0:91.7.0.255

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
  "obis_pattern": "1-0:91.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
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
      "section": "TBL-000112-R000006 Instantaneous neutral current (measured)"
    }
  ],
  "applicable_notes": [
    "C=91 identifies neutral current in the AC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value.",
    "ABNT Appendix 9 distinguishes this measured neutral current from the calculated neutral current at B=1."
  ]
}
```

## Notes

