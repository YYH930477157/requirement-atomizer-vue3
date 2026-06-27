---
id: KB-ABNT-OBIS-1-0-94-55-X-255-MONTHLY-DRP
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Monthly DRP
aliases:
- OBIS 1-0:94.55.x.255
- DRP calculation monthly
keywords:
- 1-0:94.55.x.255
- Monthly DRP
- DRP calculation monthly
- TBL-000145
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Monthly DRP

## Definition

ABNT Appendix 9 row-level COSEM object `Monthly DRP` with OBIS pattern `1-0:94.55.x.255` and interface class 3 (Register). DRP calculation monthly

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "x",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000145-R000002, TBL-000145"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000145-R000002",
    "source_refs": [
      "BLK-000902",
      "TBL-000145-R000002",
      "TBL-000145"
    ],
    "source_table_ids": [
      "TBL-000145"
    ]
  }
}
```

## Notes
