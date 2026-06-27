---
id: KB-ABNT-OBIS-1-0-94-55-184-255-TIME-TRIGGER-FOR-MONTHLY-DRP-DRC-CALCULATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Time trigger for monthly DRP/DRC calculation
aliases:
- OBIS 1-0:94.55.184.255
- Time stamp for the log in DRP It is CKD monthly
keywords:
- 1-0:94.55.184.255
- Time trigger for monthly DRP/DRC calculation
- Time stamp for the log in DRP It is CKD monthly
- TBL-000144
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
---

# Time trigger for monthly DRP/DRC calculation

## Definition

ABNT Appendix 9 row-level COSEM object `Time trigger for monthly DRP/DRC calculation` with OBIS pattern `1-0:94.55.184.255` and interface class 1 (Data). Time stamp for the log in DRP It is CKD monthly

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.184.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "184",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000144-R000018, TBL-000144"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000144-R000018",
    "source_refs": [
      "BLK-000900",
      "TBL-000144-R000018",
      "TBL-000144"
    ],
    "source_table_ids": [
      "TBL-000144"
    ]
  }
}
```

## Notes
