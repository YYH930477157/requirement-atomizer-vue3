---
id: KB-ABNT-OBIS-1-0-128-2-X-255-1-0-94-55-X-255-CUMULATIVE-DMCR-REGISTER-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Cumulative DMCR+ - Register import
aliases:
- OBIS 1-0:128.2.x.255 1-0:94.55.x.255
- Cumulative registered maximum corrected demand
keywords:
- 1-0:128.2.x.255 1-0:94.55.x.255
- Cumulative DMCR+ - Register import
- Cumulative registered maximum corrected demand
- TBL-000101
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
---

# Cumulative DMCR+ - Register import

## Definition

ABNT Appendix 9 row-level COSEM object `Cumulative DMCR+ - Register import` with OBIS pattern `1-0:128.2.x.255 1-0:94.55.x.255` and interface class 4 (Extended Register). Cumulative registered maximum corrected demand

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:128.2.x.255 1-0:94.55.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "128",
    "D": "2",
    "E": "x",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000101-R000006, TBL-000101"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000101-R000006",
    "source_refs": [
      "BLK-000798",
      "TBL-000101-R000006",
      "TBL-000101"
    ],
    "source_table_ids": [
      "TBL-000101"
    ]
  }
}
```

## Notes
