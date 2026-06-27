---
id: KB-ABNT-OBIS-0-0-94-55-111-255-BILLING-TRIGGER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Billing Trigger
aliases:
- OBIS 0-0:94.55.111.255
keywords:
- 0-0:94.55.111.255
- Billing Trigger
- TBL-000072
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Billing Trigger

## Definition

ABNT Appendix 9 row-level COSEM object `Billing Trigger` with OBIS pattern `0-0:94.55.111.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:94.55.111.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "111",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000072-R000003, TBL-000072"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000072-R000003",
    "source_refs": [
      "BLK-000730",
      "TBL-000072-R000003",
      "TBL-000072"
    ],
    "source_table_ids": [
      "TBL-000072"
    ]
  }
}
```

## Notes
