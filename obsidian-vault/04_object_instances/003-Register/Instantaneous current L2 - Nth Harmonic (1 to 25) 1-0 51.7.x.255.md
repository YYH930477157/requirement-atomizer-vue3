---
id: KB-ABNT-OBIS-1-0-51-7-X-255-INSTANTANEOUS-CURRENT-L2-NTH-HARMONIC-1-TO-25
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous current L2 - Nth Harmonic (1 to 25)
aliases:
- OBIS 1-0:51.7.x.255
keywords:
- 1-0:51.7.x.255
- Instantaneous current L2 - Nth Harmonic (1 to 25)
- TBL-000110
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Instantaneous current L2 - Nth Harmonic (1 to 25)

## Definition

ABNT Appendix 9 row-level COSEM object `Instantaneous current L2 - Nth Harmonic (1 to 25)` with OBIS pattern `1-0:51.7.x.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:51.7.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "51",
    "D": "7",
    "E": "x",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000110-R000006, TBL-000110"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000110-R000006",
    "source_refs": [
      "BLK-000828",
      "TBL-000110-R000006",
      "TBL-000110"
    ],
    "source_table_ids": [
      "TBL-000110"
    ]
  }
}
```

## Notes
