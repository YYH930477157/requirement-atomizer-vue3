---
id: KB-ABNT-OBIS-1-1-94-55-104-255-PHASE-PRESENCE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Phase presence
aliases:
- OBIS 1-1:94.55.104.255
keywords:
- 1-1:94.55.104.255
- Phase presence
- TBL-000170
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Phase presence

## Definition

ABNT Appendix 9 row-level COSEM object `Phase presence` with OBIS pattern `1-1:94.55.104.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "1-1:94.55.104.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "1",
    "C": "94",
    "D": "55",
    "E": "104",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000170-R000005, TBL-000170"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000170-R000005",
    "source_refs": [
      "BLK-000973",
      "TBL-000170-R000005",
      "TBL-000170"
    ],
    "source_table_ids": [
      "TBL-000170"
    ]
  }
}
```

## Notes
