---
id: KB-ABNT-OBIS-1-0-128-6-X-255-1-0-94-55-X-255-DMCR-REGISTER-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DMCR - Register import
aliases:
- OBIS 1-0:128.6.x.255 1-0:94.55.x.255
- Recorded corrected maximum demand
keywords:
- 1-0:128.6.x.255 1-0:94.55.x.255
- DMCR - Register import
- Recorded corrected maximum demand
- TBL-000100
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
---

# DMCR - Register import

## Definition

ABNT Appendix 9 row-level COSEM object `DMCR - Register import` with OBIS pattern `1-0:128.6.x.255 1-0:94.55.x.255` and interface class 4 (Extended Register). Recorded corrected maximum demand

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:128.6.x.255 1-0:94.55.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "128",
    "D": "6",
    "E": "x",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000100-R000002, TBL-000100"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000100-R000002",
    "source_refs": [
      "BLK-000796",
      "TBL-000100-R000002",
      "TBL-000100"
    ],
    "source_table_ids": [
      "TBL-000100"
    ]
  }
}
```

## Notes
