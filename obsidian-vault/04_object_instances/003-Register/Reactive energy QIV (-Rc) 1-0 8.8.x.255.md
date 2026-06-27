---
id: KB-ABNT-OBIS-1-0-8-8-X-255-REACTIVE-ENERGY-QIV-RC
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Reactive energy QIV (-Rc)
aliases:
- OBIS 1-0:8.8.x.255
- Absolute value
keywords:
- 1-0:8.8.x.255
- Reactive energy QIV (-Rc)
- Absolute value
- TBL-000084
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Reactive energy QIV (-Rc)

## Definition

ABNT Appendix 9 row-level COSEM object `Reactive energy QIV (-Rc)` with OBIS pattern `1-0:8.8.x.255` and interface class 3 (Register). Absolute value

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:8.8.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "8",
    "D": "8",
    "E": "x",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000084-R000002, TBL-000084"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000084-R000002",
    "source_refs": [
      "BLK-000760",
      "TBL-000084-R000002",
      "TBL-000084"
    ],
    "source_table_ids": [
      "TBL-000084"
    ]
  }
}
```

## Notes
