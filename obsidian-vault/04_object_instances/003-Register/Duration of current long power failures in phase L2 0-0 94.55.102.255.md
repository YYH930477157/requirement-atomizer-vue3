---
id: KB-ABNT-OBIS-0-0-94-55-102-255-DURATION-OF-CURRENT-LONG-POWER-FAILURES-IN-PHASE-L2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Duration of current long power failures in phase L2
aliases:
- OBIS 0-0:94.55.102.255
- time to failure current power (open) in Phase B
keywords:
- 0-0:94.55.102.255
- Duration of current long power failures in phase L2
- time to failure current power (open) in Phase B
- TBL-000049
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Duration of current long power failures in phase L2

## Definition

ABNT Appendix 9 row-level COSEM object `Duration of current long power failures in phase L2` with OBIS pattern `0-0:94.55.102.255` and interface class 3 (Register). time to failure current power (open) in Phase B

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:94.55.102.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "102",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000049-R000006, TBL-000049"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000049-R000006",
    "source_refs": [
      "BLK-000664",
      "TBL-000049-R000006",
      "TBL-000049"
    ],
    "source_table_ids": [
      "TBL-000049"
    ]
  }
}
```

## Notes
