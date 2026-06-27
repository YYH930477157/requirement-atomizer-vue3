---
id: KB-ABNT-OBIS-1-1-94-55-103-255-ACTIVE-QUADRANT-L3
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active Quadrant L3
aliases:
- OBIS 1-1:94.55.103.255
keywords:
- 1-1:94.55.103.255
- Active Quadrant L3
- TBL-000170
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Active Quadrant L3

## Definition

ABNT Appendix 9 row-level COSEM object `Active Quadrant L3` with OBIS pattern `1-1:94.55.103.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "1-1:94.55.103.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "1",
    "C": "94",
    "D": "55",
    "E": "103",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000170-R000002, TBL-000170"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000170-R000002",
    "source_refs": [
      "BLK-000973",
      "TBL-000170-R000002",
      "TBL-000170"
    ],
    "source_table_ids": [
      "TBL-000170"
    ]
  }
}
```

## Notes
