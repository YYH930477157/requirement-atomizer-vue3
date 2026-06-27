---
id: KB-ABNT-OBIS-1-0-1-3-X-255-CUMULATIVE-REACTIVE-DEMAND-REGISTER-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Cumulative Reactive Demand+ - Register import
aliases:
- OBIS 1-0:1.3.x.255
keywords:
- 1-0:1.3.x.255
- Cumulative Reactive Demand+ - Register import
- TBL-000097
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
---

# Cumulative Reactive Demand+ - Register import

## Definition

ABNT Appendix 9 row-level COSEM object `Cumulative Reactive Demand+ - Register import` with OBIS pattern `1-0:1.3.x.255` and interface class 4 (Extended Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:1.3.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "1",
    "D": "3",
    "E": "x",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000097-R000006, TBL-000097"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000097-R000006",
    "source_refs": [
      "BLK-000790",
      "TBL-000097-R000006",
      "TBL-000097"
    ],
    "source_table_ids": [
      "TBL-000097"
    ]
  }
}
```

## Notes
