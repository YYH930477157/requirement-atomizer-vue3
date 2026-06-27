---
id: KB-ABNT-OBIS-1-0-52-32-0-255-NUMBER-OF-VOLTAGE-SAGS-IN-PHASE-L2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Number of voltage sags in phase L2
aliases:
- OBIS 1-0:52.32.0.255
keywords:
- 1-0:52.32.0.255
- Number of voltage sags in phase L2
- TBL-000133
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Number of voltage sags in phase L2

## Definition

ABNT Appendix 9 row-level COSEM object `Number of voltage sags in phase L2` with OBIS pattern `1-0:52.32.0.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:52.32.0.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "52",
    "D": "32",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000133-R000014, TBL-000133"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000133-R000014",
    "source_refs": [
      "BLK-000878",
      "TBL-000133-R000014",
      "TBL-000133"
    ],
    "source_table_ids": [
      "TBL-000133"
    ]
  }
}
```

## Notes
