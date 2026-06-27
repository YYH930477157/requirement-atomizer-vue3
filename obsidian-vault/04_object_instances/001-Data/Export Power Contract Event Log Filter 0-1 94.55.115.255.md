---
id: KB-ABNT-OBIS-0-1-94-55-115-255-EXPORT-POWER-CONTRACT-EVENT-LOG-FILTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Export Power Contract Event Log Filter
aliases:
- OBIS 0-1:94.55.115.255
- Contract Event Log Filter export of energy it contains enabling logging and enabling
  notification of event
keywords:
- 0-1:94.55.115.255
- Export Power Contract Event Log Filter
- Contract Event Log Filter export of energy it contains enabling logging and enabling
  notification of event
- TBL-000062
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Export Power Contract Event Log Filter

## Definition

ABNT Appendix 9 row-level COSEM object `Export Power Contract Event Log Filter` with OBIS pattern `0-1:94.55.115.255` and interface class 1 (Data). Contract Event Log Filter export of energy it contains enabling logging and enabling notification of event

## Structured Data

```json metadata
{
  "obis_pattern": "0-1:94.55.115.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "1",
    "C": "94",
    "D": "55",
    "E": "115",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000062-R000003, TBL-000062"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000062-R000003",
    "source_refs": [
      "BLK-000698",
      "TBL-000062-R000003",
      "TBL-000062"
    ],
    "source_table_ids": [
      "TBL-000062"
    ]
  }
}
```

## Notes
