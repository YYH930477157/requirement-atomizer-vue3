---
id: KB-OBIS-1-0-128-6-X-255-DMCR-REGISTER-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DMCR - Register import
aliases:
- OBIS 1-0:128.6.x.255
- Recorded corrected maximum demand
keywords:
- 1-0:128.6.x.255
- DMCR - Register import
- recorded corrected maximum demand
- TBL-000100
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# DMCR - Register import

## Definition

Row-level Extended Register object holding the Brazil ABNT `DMCR` (Recorded corrected maximum demand) per tariff, at logical name `1-0:128.6.x.255`. ABNT Appendix 9 (NBR 16968:2022) registers this object under two equivalent codes: the main code `1-0:128.6.x.255` (this entry) and the country-specific code `1-0:94.55.x.255` (separate entry).

## Aliases

- OBIS 1-0:128.6.x.255
- Recorded corrected maximum demand

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-4-EXTENDED-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:128.6.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "128 Brazil-specific measurement object",
    "D": "6 maximum demand",
    "E": "x tariff/rate index (templated)",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 14,
    "title": "Value group D codes - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 14 Value group D codes - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "DMCR - Register import at 1-0:128.6.x.255 (TBL-000100-R000002); country-specific equivalent 1-0:94.55.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about the per-tariff DMCR (recorded corrected maximum demand) Brazil-specific demand measurement.",
    "ABNT Appendix 9 (NBR 16968:2022) describes this object as DMCR (Recorded corrected maximum demand). The Blue Book covers only the value-group structure (D code 6 maximum demand); it does not name this Brazil-specific object."
  ]
}
```

## Notes
