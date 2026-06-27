---
id: KB-OBIS-1-0-90-7-0-255-INSTANT-CURRENT-TOTAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instant current (sum over all phases)
aliases:
- Instantaneous current of total
- Total instantaneous current
- OBIS 1-0:90.7.0.255
keywords:
- 1-0:90.7.0.255
- Instant current (sum over all phases)
- instantaneous current of total
- total instantaneous current
- current sum over all phases
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

# Instant current (sum over all phases)

## Definition

Row-level OBIS object for AC electricity instantaneous current summed over all phases, represented by logical name pattern `1-0:90.7.0.255`.

## Aliases

- Instantaneous current of total
- Total instantaneous current
- OBIS 1-0:90.7.0.255

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
  "obis_pattern": "1-0:90.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "90 current sum over all phases",
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
      "section": "Table 13 AC electricity C=90 current total; Table 14 D=7 instantaneous value"
    },
    {
      "source": "ABNT Appendix 9 extracted table TBL-000112",
      "section": "TBL-000112-R000002 Instant current (sum over all phases)"
    }
  ],
  "applicable_notes": [
    "C=90 identifies current summed over all phases in the AC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value.",
    "ABNT Appendix 9 uses this row for Instant current (sum over all phases)."
  ]
}
```

## Notes

