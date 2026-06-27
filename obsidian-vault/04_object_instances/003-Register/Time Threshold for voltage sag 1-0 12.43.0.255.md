---
id: KB-ABNT-OBIS-1-0-12-43-0-255-TIME-THRESHOLD-FOR-VOLTAGE-SAG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Time Threshold for voltage sag
aliases:
- OBIS 1-0:12.43.0.255
keywords:
- 1-0:12.43.0.255
- Time Threshold for voltage sag
- TBL-000131
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Time Threshold for voltage sag

## Definition

ABNT Appendix 9 row-level COSEM object `Time Threshold for voltage sag` with OBIS pattern `1-0:12.43.0.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:12.43.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "12",
    "D": "43",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000131-R000010, TBL-000131"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000131-R000010",
    "source_refs": [
      "BLK-000874",
      "TBL-000131-R000010",
      "TBL-000131"
    ],
    "source_table_ids": [
      "TBL-000131"
    ]
  }
}
```

## Notes
