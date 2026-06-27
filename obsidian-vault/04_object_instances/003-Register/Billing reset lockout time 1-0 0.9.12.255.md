---
id: KB-ABNT-OBIS-1-0-0-9-12-255-BILLING-RESET-LOCKOUT-TIME
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Billing reset lockout time
aliases:
- OBIS 1-0:0.9.12.255
keywords:
- 1-0:0.9.12.255
- Billing reset lockout time
- TBL-000172
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Billing reset lockout time

## Definition

ABNT Appendix 9 row-level COSEM object `Billing reset lockout time` with OBIS pattern `1-0:0.9.12.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:0.9.12.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "0",
    "D": "9",
    "E": "12",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000172-R000004, TBL-000172"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000172-R000004",
    "source_refs": [
      "BLK-000977",
      "TBL-000172-R000004",
      "TBL-000172"
    ],
    "source_table_ids": [
      "TBL-000172"
    ]
  }
}
```

## Notes
