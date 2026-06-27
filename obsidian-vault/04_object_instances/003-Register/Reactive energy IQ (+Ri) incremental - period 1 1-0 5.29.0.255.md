---
id: KB-ABNT-OBIS-1-0-5-29-0-255-REACTIVE-ENERGY-IQ-RI-INCREMENTAL-PERIOD-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Reactive energy IQ (+Ri) incremental - period 1
aliases:
- OBIS 1-0:5.29.0.255
- value for the load profile - period 1
keywords:
- 1-0:5.29.0.255
- Reactive energy IQ (+Ri) incremental - period 1
- value for the load profile - period 1
- TBL-000080
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Reactive energy IQ (+Ri) incremental - period 1

## Definition

ABNT Appendix 9 row-level COSEM object `Reactive energy IQ (+Ri) incremental - period 1` with OBIS pattern `1-0:5.29.0.255` and interface class 3 (Register). value for the load profile - period 1

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:5.29.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "5",
    "D": "29",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000080-R000008, TBL-000080"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000080-R000008",
    "source_refs": [
      "BLK-000752",
      "TBL-000080-R000008",
      "TBL-000080"
    ],
    "source_table_ids": [
      "TBL-000080"
    ]
  }
}
```

## Notes
