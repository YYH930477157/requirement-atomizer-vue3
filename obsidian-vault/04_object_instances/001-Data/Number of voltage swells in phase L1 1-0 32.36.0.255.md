---
id: KB-ABNT-OBIS-1-0-32-36-0-255-NUMBER-OF-VOLTAGE-SWELLS-IN-PHASE-L1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Number of voltage swells in phase L1
aliases:
- OBIS 1-0:32.36.0.255
keywords:
- 1-0:32.36.0.255
- Number of voltage swells in phase L1
- TBL-000137
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Number of voltage swells in phase L1

## Definition

ABNT Appendix 9 row-level COSEM object `Number of voltage swells in phase L1` with OBIS pattern `1-0:32.36.0.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:32.36.0.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "32",
    "D": "36",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000137-R000008, TBL-000137"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000137-R000008",
    "source_refs": [
      "BLK-000886",
      "TBL-000137-R000008",
      "TBL-000137"
    ],
    "source_table_ids": [
      "TBL-000137"
    ]
  }
}
```

## Notes
