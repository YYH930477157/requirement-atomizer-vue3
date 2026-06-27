---
id: KB-ABNT-OBIS-1-1-94-55-102-255-ACTIVE-QUADRANT-L2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active Quadrant L2
aliases:
- OBIS 1-1:94.55.102.255
keywords:
- 1-1:94.55.102.255
- Active Quadrant L2
- TBL-000169
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Active Quadrant L2

## Definition

ABNT Appendix 9 row-level COSEM object `Active Quadrant L2` with OBIS pattern `1-1:94.55.102.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "1-1:94.55.102.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "1",
    "C": "94",
    "D": "55",
    "E": "102",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000169-R000008, TBL-000169"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000169-R000008",
    "source_refs": [
      "BLK-000971",
      "TBL-000169-R000008",
      "TBL-000169"
    ],
    "source_table_ids": [
      "TBL-000169"
    ]
  }
}
```

## Notes
