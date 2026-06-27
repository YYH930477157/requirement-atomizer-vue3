---
id: KB-ABNT-OBIS-1-0-91-44-1-255-TIME-THRESHOLD-NEUTRAL-CURRENT-DIFF-ABSOLUTE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Time threshold neutral current diff (absolute)
aliases:
- OBIS 1-0:91.44.1.255
keywords:
- 1-0:91.44.1.255
- Time threshold neutral current diff (absolute)
- TBL-000168
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Time threshold neutral current diff (absolute)

## Definition

ABNT Appendix 9 row-level COSEM object `Time threshold neutral current diff (absolute)` with OBIS pattern `1-0:91.44.1.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:91.44.1.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "91",
    "D": "44",
    "E": "1",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000168-R000012, TBL-000168"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000168-R000012",
    "source_refs": [
      "BLK-000964",
      "TBL-000168-R000012",
      "TBL-000168"
    ],
    "source_table_ids": [
      "TBL-000168"
    ]
  }
}
```

## Notes
