---
id: KB-ABNT-OBIS-1-0-91-50-0-255-NEUTRAL-AVERAGE-CURRENT-PERIOD-2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Neutral average current - period 2
aliases:
- OBIS 1-0:91.50.0.255
keywords:
- 1-0:91.50.0.255
- Neutral average current - period 2
- TBL-000151
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Neutral average current - period 2

## Definition

ABNT Appendix 9 row-level COSEM object `Neutral average current - period 2` with OBIS pattern `1-0:91.50.0.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:91.50.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "91",
    "D": "50",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000151-R000006, TBL-000151"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000151-R000006",
    "source_refs": [
      "BLK-000918",
      "TBL-000151-R000006",
      "TBL-000151"
    ],
    "source_table_ids": [
      "TBL-000151"
    ]
  }
}
```

## Notes
