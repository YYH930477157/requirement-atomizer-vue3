---
id: KB-ABNT-OBIS-1-0-94-55-173-255-TIME-TRIGGER-FOR-DRP-DRC-CALCULATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Time trigger for DRP/DRC calculation
aliases:
- OBIS 1-0:94.55.173.255
- Timestamp for DRP log and CKD
keywords:
- 1-0:94.55.173.255
- Time trigger for DRP/DRC calculation
- Timestamp for DRP log and CKD
- TBL-000141
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Time trigger for DRP/DRC calculation

## Definition

ABNT Appendix 9 row-level COSEM object `Time trigger for DRP/DRC calculation` with OBIS pattern `1-0:94.55.173.255` and interface class 1 (Data). Timestamp for DRP log and CKD

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.173.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "173",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000141-R000011, TBL-000141"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000141-R000011",
    "source_refs": [
      "BLK-000894",
      "TBL-000141-R000011",
      "TBL-000141"
    ],
    "source_table_ids": [
      "TBL-000141"
    ]
  }
}
```

## Notes
