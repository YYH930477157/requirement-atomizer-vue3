---
id: KB-ABNT-OBIS-0-0-43-1-5-255-SECURITY-INVOCATION-COUNTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Security-Invocation counter
aliases:
- OBIS 0-0:43.1.5.255
- Summon Counter in reception - " unicast " key (remote)
keywords:
- 0-0:43.1.5.255
- Security-Invocation counter
- Summon Counter in reception - " unicast " key (remote)
- TBL-000036
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Security-Invocation counter

## Definition

ABNT Appendix 9 row-level COSEM object `Security-Invocation counter` with OBIS pattern `0-0:43.1.5.255` and interface class 1 (Data). Summon Counter in reception - " unicast " key (remote)

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:43.1.5.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "43",
    "D": "1",
    "E": "5",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000036-R000003, TBL-000036"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000036-R000003",
    "source_refs": [
      "BLK-000618",
      "TBL-000036-R000003",
      "TBL-000036"
    ],
    "source_table_ids": [
      "TBL-000036"
    ]
  }
}
```

## Notes
