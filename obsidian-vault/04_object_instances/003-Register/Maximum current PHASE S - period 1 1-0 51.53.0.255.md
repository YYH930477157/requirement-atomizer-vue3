---
id: KB-ABNT-OBIS-1-0-51-53-0-255-MAXIMUM-CURRENT-PHASE-S-PERIOD-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Maximum current PHASE S - period 1
aliases:
- OBIS 1-0:51.53.0.255
keywords:
- 1-0:51.53.0.255
- Maximum current PHASE S - period 1
- TBL-000158
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Maximum current PHASE S - period 1

## Definition

ABNT Appendix 9 row-level COSEM object `Maximum current PHASE S - period 1` with OBIS pattern `1-0:51.53.0.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:51.53.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "51",
    "D": "53",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000158-R000010, TBL-000158"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000158-R000010",
    "source_refs": [
      "BLK-000936",
      "TBL-000158-R000010",
      "TBL-000158"
    ],
    "source_table_ids": [
      "TBL-000158"
    ]
  }
}
```

## Notes
