---
id: KB-ABNT-OBIS-1-0-94-55-91-255-DURATION-OF-VOLTAGE-SAGS-FOR-AVERAGE-VOLTAGE-IN-ALL-3-PHASES
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Duration of voltage sags for average voltage in all 3 phases
aliases:
- OBIS 1-0:94.55.91.255
keywords:
- 1-0:94.55.91.255
- Duration of voltage sags for average voltage in all 3 phases
- TBL-000135
domain_tags:
- cosem_object
- ac_electricity
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Duration of voltage sags for average voltage in all 3 phases

## Definition

ABNT Appendix 9 row-level COSEM object `Duration of voltage sags for average voltage in all 3 phases` with OBIS pattern `1-0:94.55.91.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.91.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "91",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000135-R000011, TBL-000135"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000135-R000011",
    "source_refs": [
      "BLK-000882",
      "TBL-000135-R000011",
      "TBL-000135"
    ],
    "source_table_ids": [
      "TBL-000135"
    ]
  }
}
```

## Notes
