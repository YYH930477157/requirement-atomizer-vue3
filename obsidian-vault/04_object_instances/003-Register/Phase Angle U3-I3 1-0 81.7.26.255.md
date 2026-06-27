---
id: KB-ABNT-OBIS-1-0-81-7-26-255-PHASE-ANGLE-U3-I3
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Phase Angle U3-I3
aliases:
- OBIS 1-0:81.7.26.255
keywords:
- 1-0:81.7.26.255
- Phase Angle U3-I3
- TBL-000129
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Phase Angle U3-I3

## Definition

ABNT Appendix 9 row-level COSEM object `Phase Angle U3-I3` with OBIS pattern `1-0:81.7.26.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:81.7.26.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "81",
    "D": "7",
    "E": "26",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000129-R000012, TBL-000129"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000129-R000012",
    "source_refs": [
      "BLK-000866",
      "TBL-000129-R000012",
      "TBL-000129"
    ],
    "source_table_ids": [
      "TBL-000129"
    ]
  }
}
```

## Notes
