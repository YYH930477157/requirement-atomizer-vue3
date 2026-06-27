---
id: KB-ABNT-OBIS-0-0-97-98-0-255-ALARM-OBJECT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Alarm Object
aliases:
- OBIS 0-0:97.98.0.255
- Alarm log
keywords:
- 0-0:97.98.0.255
- Alarm Object
- Alarm log
- TBL-000051
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Alarm Object

## Definition

ABNT Appendix 9 row-level COSEM object `Alarm Object` with OBIS pattern `0-0:97.98.0.255` and interface class 3 (Register). Alarm log

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:97.98.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "97",
    "D": "98",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000051-R000005, TBL-000051"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000051-R000005",
    "source_refs": [
      "BLK-000672",
      "TBL-000051-R000005",
      "TBL-000051"
    ],
    "source_table_ids": [
      "TBL-000051"
    ]
  }
}
```

## Notes
