---
id: KB-ABNT-OBIS-0-0-96-7-7-255-NUMBER-OF-LONG-POWER-FAILURES-IN-PHASE-L2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Number of long power failures in phase L2
aliases:
- OBIS 0-0:96.7.7.255
keywords:
- 0-0:96.7.7.255
- Number of long power failures in phase L2
- TBL-000050
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Number of long power failures in phase L2

## Definition

ABNT Appendix 9 row-level COSEM object `Number of long power failures in phase L2` with OBIS pattern `0-0:96.7.7.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.7.7.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "96",
    "D": "7",
    "E": "7",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000050-R000002, TBL-000050"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000050-R000002",
    "source_refs": [
      "BLK-000666",
      "TBL-000050-R000002",
      "TBL-000050"
    ],
    "source_table_ids": [
      "TBL-000050"
    ]
  }
}
```

## Notes
