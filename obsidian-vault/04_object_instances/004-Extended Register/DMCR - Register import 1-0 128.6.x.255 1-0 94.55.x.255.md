---
id: KB-ABNT-OBIS-1-0-128-6-X-255-1-0-94-55-X-255-DMCR-REGISTER-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DMCR - Register import
aliases:
- OBIS 1-0:128.6.x.255 1-0:94.55.x.255
- Recorded corrected maximum demand
keywords:
- 1-0:128.6.x.255 1-0:94.55.x.255
- DMCR - Register import
- Recorded corrected maximum demand
- TBL-000100
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
---

# DMCR - Register import

## Definition

Row-level Extended Register object. ABNT Appendix 9 (NBR 16968:2022) Brazil-specific object `DMCR - Register import` (recorded corrected maximum demand). The stored OBIS pattern merges two OBIS codes (`1-0:128.6.x.255` and `1-0:94.55.x.255`) into one entry — this is an extraction artifact that needs source re-check before the canonical single OBIS can be confirmed.

## Aliases

- OBIS 1-0:128.6.x.255 1-0:94.55.x.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-4-EXTENDED-REGISTER`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:128.6.x.255 1-0:94.55.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "128 (first of two merged OBIS) / 94 country-specific",
    "D": "6 maximum demand / 55 country-specific",
    "E": "x tariff/rate index (templated)",
    "F": "255 current value"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "DMCR - Register import at 1-0:128.6.x.255 1-0:94.55.x.255 (TBL-000100)"
    }
  ],
  "applicable_notes": [
    "Extraction artifact: two OBIS patterns (1-0:128.6.x.255 and 1-0:94.55.x.255) are merged into this single entry. Needs source re-check against ABNT Appendix 9 to determine the canonical single OBIS before this row can be fully curated with a Blue Book table reference.",
    "ABNT Appendix 9 describes this object as the recorded corrected maximum demand (DMCR), a Brazil-specific demand object."
  ]
}
```

## Notes

- FLAGGED: merged two-OBIS extraction artifact; blue_book_table_ref intentionally left unset pending source re-check (per §5.6). obis_pattern is frozen as-is because the exact-OBIS gate depends on it.
