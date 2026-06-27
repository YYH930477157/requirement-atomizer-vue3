---
id: KB-ABNT-OBIS-0-0-96-10-1-255-INSTANTANEOUS-PHASE-SEQUENCE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous phase sequence
aliases:
- OBIS 0-0:96.10.1.255
keywords:
- 0-0:96.10.1.255
- Instantaneous phase sequence
- TBL-000125
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Instantaneous phase sequence

## Definition

ABNT Appendix 9 row-level COSEM object `Instantaneous phase sequence` with OBIS pattern `0-0:96.10.1.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.10.1.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "96",
    "D": "10",
    "E": "1",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000125-R000002, TBL-000125"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000125-R000002",
    "source_refs": [
      "BLK-000858",
      "TBL-000125-R000002",
      "TBL-000125"
    ],
    "source_table_ids": [
      "TBL-000125"
    ]
  }
}
```

## Notes
