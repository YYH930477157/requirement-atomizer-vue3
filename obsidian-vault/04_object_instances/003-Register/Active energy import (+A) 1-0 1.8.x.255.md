---
id: KB-ABNT-OBIS-1-0-1-8-X-255-ACTIVE-ENERGY-IMPORT-A
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active energy import (+A)
aliases:
- OBIS 1-0:1.8.x.255
- Absolute value
keywords:
- 1-0:1.8.x.255
- Active energy import (+A)
- Absolute value
- TBL-000077
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Active energy import (+A)

## Definition

ABNT Appendix 9 row-level COSEM object `Active energy import (+A)` with OBIS pattern `1-0:1.8.x.255` and interface class 3 (Register). Absolute value

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:1.8.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "1",
    "D": "8",
    "E": "x",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000077-R000002, TBL-000077"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000077-R000002",
    "source_refs": [
      "BLK-000746",
      "TBL-000077-R000002",
      "TBL-000077"
    ],
    "source_table_ids": [
      "TBL-000077"
    ]
  }
}
```

## Notes
