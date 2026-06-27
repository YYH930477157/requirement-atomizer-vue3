---
id: KB-ABNT-OBIS-0-0-96-7-18-255-DURATION-OF-ALL-LONG-POWER-FAILURES-IN-PHASE-L3
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Duration of all long power failures in phase L3
aliases:
- OBIS 0-0:96.7.18.255
- time for all long power outages, from the origin, in Phase C
keywords:
- 0-0:96.7.18.255
- Duration of all long power failures in phase L3
- time for all long power outages, from the origin, in Phase C
- TBL-000048
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Duration of all long power failures in phase L3

## Definition

ABNT Appendix 9 row-level COSEM object `Duration of all long power failures in phase L3` with OBIS pattern `0-0:96.7.18.255` and interface class 3 (Register). time for all long power outages, from the origin, in Phase C

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.7.18.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "96",
    "D": "7",
    "E": "18",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000048-R000010, TBL-000048"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000048-R000010",
    "source_refs": [
      "BLK-000662",
      "TBL-000048-R000010",
      "TBL-000048"
    ],
    "source_table_ids": [
      "TBL-000048"
    ]
  }
}
```

## Notes
