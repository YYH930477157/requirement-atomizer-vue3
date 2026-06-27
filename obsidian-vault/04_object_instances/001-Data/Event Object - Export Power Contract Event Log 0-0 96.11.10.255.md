---
id: KB-ABNT-OBIS-0-0-96-11-10-255-EVENT-OBJECT-EXPORT-POWER-CONTRACT-EVENT-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Event Object - Export Power Contract Event Log
aliases:
- OBIS 0-0:96.11.10.255
keywords:
- 0-0:96.11.10.255
- Event Object - Export Power Contract Event Log
- TBL-000055
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Event Object - Export Power Contract Event Log

## Definition

ABNT Appendix 9 row-level COSEM object `Event Object - Export Power Contract Event Log` with OBIS pattern `0-0:96.11.10.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.11.10.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "96",
    "D": "11",
    "E": "10",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000055-R000008, TBL-000055"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000055-R000008",
    "source_refs": [
      "BLK-000684",
      "TBL-000055-R000008",
      "TBL-000055"
    ],
    "source_table_ids": [
      "TBL-000055"
    ]
  }
}
```

## Notes
