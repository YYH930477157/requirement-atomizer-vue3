---
id: KB-ABNT-OBIS-1-0-15-7-0-255-INSTANTANEOUS-ACTIVE-POWER-Q1-Q2-Q3-Q4-L1-L2-L3-SUMM-OF-ALL-PHASES
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous active power (Q1 + Q2 + Q3 + Q4) (L1 + L2 + L3) (Summ of all phases)
aliases:
- OBIS 1-0:15.7.0.255
keywords:
- 1-0:15.7.0.255
- Instantaneous active power (Q1 + Q2 + Q3 + Q4) (L1 + L2 + L3) (Summ of all phases)
- TBL-000120
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Instantaneous active power (Q1 + Q2 + Q3 + Q4) (L1 + L2 + L3) (Summ of all phases)

## Definition

ABNT Appendix 9 row-level COSEM object `Instantaneous active power (Q1 + Q2 + Q3 + Q4) (L1 + L2 + L3) (Summ of all phases)` with OBIS pattern `1-0:15.7.0.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:15.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "15",
    "D": "7",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000120-R000012, TBL-000120"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000120-R000012",
    "source_refs": [
      "BLK-000848",
      "TBL-000120-R000012",
      "TBL-000120"
    ],
    "source_table_ids": [
      "TBL-000120"
    ]
  }
}
```

## Notes
