---
id: KB-ABNT-OBIS-0-0-94-55-100-255-DURATION-OF-CURRENT-LONG-POWER-FAILURES-IN-ANY-PHASES
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Duration of current long power failures in any phases
aliases:
- OBIS 0-0:94.55.100.255
- time to failure of current (open) power in any phase
keywords:
- 0-0:94.55.100.255
- Duration of current long power failures in any phases
- time to failure of current (open) power in any phase
- TBL-000048
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Duration of current long power failures in any phases

## Definition

ABNT Appendix 9 row-level COSEM object `Duration of current long power failures in any phases` with OBIS pattern `0-0:94.55.100.255` and interface class 3 (Register). time to failure of current (open) power in any phase

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:94.55.100.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "100",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000048-R000014, TBL-000048"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000048-R000014",
    "source_refs": [
      "BLK-000662",
      "TBL-000048-R000014",
      "TBL-000048"
    ],
    "source_table_ids": [
      "TBL-000048"
    ]
  }
}
```

## Notes
