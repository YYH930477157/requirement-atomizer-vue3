---
id: KB-ABNT-OBIS-1-0-2-8-X-255-ACTIVE-ENERGY-EXPORT-A
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active energy export ( - A)
aliases:
- OBIS 1-0:2.8.x.255
- Absolute value
keywords:
- 1-0:2.8.x.255
- Active energy export ( - A)
- Absolute value
- TBL-000078
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Active energy export ( - A)

## Definition

ABNT Appendix 9 row-level COSEM object `Active energy export ( - A)` with OBIS pattern `1-0:2.8.x.255` and interface class 3 (Register). Absolute value

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:2.8.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "2",
    "D": "8",
    "E": "x",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000078-R000008, TBL-000078"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000078-R000008",
    "source_refs": [
      "BLK-000748",
      "TBL-000078-R000008",
      "TBL-000078"
    ],
    "source_table_ids": [
      "TBL-000078"
    ]
  }
}
```

## Notes
