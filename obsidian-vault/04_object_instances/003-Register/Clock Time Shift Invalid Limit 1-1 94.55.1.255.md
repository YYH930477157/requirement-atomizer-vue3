---
id: KB-ABNT-OBIS-1-1-94-55-1-255-CLOCK-TIME-SHIFT-INVALID-LIMIT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Clock Time Shift Invalid Limit
aliases:
- OBIS 1-1:94.55.1.255
keywords:
- 1-1:94.55.1.255
- Clock Time Shift Invalid Limit
- TBL-000171
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Clock Time Shift Invalid Limit

## Definition

ABNT Appendix 9 row-level COSEM object `Clock Time Shift Invalid Limit` with OBIS pattern `1-1:94.55.1.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-1:94.55.1.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "1",
    "C": "94",
    "D": "55",
    "E": "1",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000171-R000013, TBL-000171"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000171-R000013",
    "source_refs": [
      "BLK-000975",
      "TBL-000171-R000013",
      "TBL-000171"
    ],
    "source_table_ids": [
      "TBL-000171"
    ]
  }
}
```

## Notes
