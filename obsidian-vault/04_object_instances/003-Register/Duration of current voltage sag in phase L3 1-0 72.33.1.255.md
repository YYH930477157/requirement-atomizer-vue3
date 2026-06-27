---
id: KB-ABNT-OBIS-1-0-72-33-1-255-DURATION-OF-CURRENT-VOLTAGE-SAG-IN-PHASE-L3
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Duration of current voltage sag in phase L3
aliases:
- OBIS 1-0:72.33.1.255
keywords:
- 1-0:72.33.1.255
- Duration of current voltage sag in phase L3
- TBL-000135
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Duration of current voltage sag in phase L3

## Definition

ABNT Appendix 9 row-level COSEM object `Duration of current voltage sag in phase L3` with OBIS pattern `1-0:72.33.1.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:72.33.1.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "72",
    "D": "33",
    "E": "1",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000135-R000004, TBL-000135"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000135-R000004",
    "source_refs": [
      "BLK-000882",
      "TBL-000135-R000004",
      "TBL-000135"
    ],
    "source_table_ids": [
      "TBL-000135"
    ]
  }
}
```

## Notes
