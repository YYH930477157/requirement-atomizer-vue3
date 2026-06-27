---
id: KB-ABNT-OBIS-0-0-11-0-0-255-SPECIAL-DAYS-TABLE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Special Days Table
aliases:
- OBIS 0-0:11.0.0.255
keywords:
- 0-0:11.0.0.255
- Special Days Table
- TBL-000044
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-11-SPECIAL-DAYS-TABLE
---

# Special Days Table

## Definition

ABNT Appendix 9 row-level COSEM object `Special Days Table` with OBIS pattern `0-0:11.0.0.255` and interface class 11 (Special Days Table).

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:11.0.0.255",
  "likely_interface_class_id": 11,
  "likely_interface_class_name": "Special Days Table",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "11",
    "D": "0",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000044-R000013, TBL-000044"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000044-R000013",
    "source_refs": [
      "BLK-000646",
      "TBL-000044-R000013",
      "TBL-000044"
    ],
    "source_table_ids": [
      "TBL-000044"
    ]
  }
}
```

## Notes
