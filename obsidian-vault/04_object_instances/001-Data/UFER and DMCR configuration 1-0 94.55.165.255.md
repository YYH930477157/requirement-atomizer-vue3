---
id: KB-ABNT-OBIS-1-0-94-55-165-255-UFER-AND-DMCR-CONFIGURATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: UFER and DMCR configuration
aliases:
- OBIS 1-0:94.55.165.255
- Surplus Calculation Configuration Reactive (UFER It is DMCR)
keywords:
- 1-0:94.55.165.255
- UFER and DMCR configuration
- Surplus Calculation Configuration Reactive (UFER It is DMCR)
- TBL-000173
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# UFER and DMCR configuration

## Definition

ABNT Appendix 9 row-level COSEM object `UFER and DMCR configuration` with OBIS pattern `1-0:94.55.165.255` and interface class 1 (Data). Surplus Calculation Configuration Reactive (UFER It is DMCR)

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.165.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "165",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000173-R000002, TBL-000173"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000173-R000002",
    "source_refs": [
      "BLK-000979",
      "TBL-000173-R000002",
      "TBL-000173"
    ],
    "source_table_ids": [
      "TBL-000173"
    ]
  }
}
```

## Notes
