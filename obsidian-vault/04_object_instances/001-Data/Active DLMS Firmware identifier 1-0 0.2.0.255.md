---
id: KB-ABNT-OBIS-1-0-0-2-0-255-ACTIVE-DLMS-FIRMWARE-IDENTIFIER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active DLMS Firmware identifier
aliases:
- OBIS 1-0:0.2.0.255
keywords:
- 1-0:0.2.0.255
- Active DLMS Firmware identifier
- TBL-000172
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Active DLMS Firmware identifier

## Definition

ABNT Appendix 9 row-level COSEM object `Active DLMS Firmware identifier` with OBIS pattern `1-0:0.2.0.255` and interface class 1 (Data).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:0.2.0.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "0",
    "D": "2",
    "E": "0",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000172-R000011, TBL-000172"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000172-R000011",
    "source_refs": [
      "BLK-000977",
      "TBL-000172-R000011",
      "TBL-000172"
    ],
    "source_table_ids": [
      "TBL-000172"
    ]
  }
}
```

## Notes
