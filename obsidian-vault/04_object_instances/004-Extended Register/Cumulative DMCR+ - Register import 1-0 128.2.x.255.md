---
id: KB-OBIS-1-0-128-2-X-255-CUMULATIVE-DMCR-REGISTER-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Cumulative DMCR+ - Register import
aliases:
- OBIS 1-0:128.2.x.255
- Cumulative registered maximum corrected demand
keywords:
- 1-0:128.2.x.255
- Cumulative DMCR+ - Register import
- cumulative registered maximum corrected demand
- TBL-000101
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Cumulative DMCR+ - Register import

## Definition

Row-level Extended Register object holding the Brazil ABNT `Cumulative DMCR+` (Cumulative registered maximum corrected demand) per tariff, at logical name `1-0:128.2.x.255`. ABNT Appendix 9 (NBR 16968:2022) registers this object under two equivalent codes: the main code `1-0:128.2.x.255` (this entry) and the country-specific code `1-0:94.55.x.255` (separate entry).

## Aliases

- OBIS 1-0:128.2.x.255
- Cumulative registered maximum corrected demand

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-4-EXTENDED-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:128.2.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "128 Brazil-specific measurement object",
    "D": "2 rate",
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
      "section": "Cumulative DMCR+ - Register import at 1-0:128.2.x.255 (TBL-000101-R000006); country-specific equivalent 1-0:94.55.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about the per-tariff Cumulative DMCR+ (cumulative registered maximum corrected demand) Brazil-specific demand measurement.",
    "ABNT Appendix 9 (NBR 16968:2022) describes this object as Cumulative DMCR+ (Cumulative registered maximum corrected demand). The Blue Book covers only the value-group structure (D code 2 rate); it does not name this Brazil-specific object."
  ]
}
```

## Notes
