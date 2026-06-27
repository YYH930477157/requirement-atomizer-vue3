---
id: KB-ABNT-OBIS-0-0-94-55-55-255-TIMEOUT-OPEN-SESSION-FOR-SECURITY-CLIENT-THROUGH-PLC-CHANNEL-FOR-CURRENT-ASSOCIATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Timeout open session for security client through PLC channel for current association
aliases:
- OBIS 0-0:94.55.55.255
keywords:
- 0-0:94.55.55.255
- Timeout open session for security client through PLC channel for current association
- TBL-000073
domain_tags:
- cosem_object
- general
- abnt_bulk_import
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
---

# Timeout open session for security client through PLC channel for current association

## Definition

ABNT Appendix 9 row-level COSEM object `Timeout open session for security client through PLC channel for current association` with OBIS pattern `0-0:94.55.55.255` and interface class 3 (Register).

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:94.55.55.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0",
    "B": "0",
    "C": "94",
    "D": "55",
    "E": "55",
    "F": "255"
  },
  "source_refs": [
    {
      "source": "ABNT Appendix 9 extracted COSEM object model",
      "section": "TBL-000073-R000008, TBL-000073"
    }
  ],
  "applicable_notes": [
    "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
    "Review against Blue Book semantics before treating this row as manually curated."
  ],
  "bulk_import": {
    "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
    "source_item_id": "TBL-000073-R000008",
    "source_refs": [
      "BLK-000732",
      "TBL-000073-R000008",
      "TBL-000073"
    ],
    "source_table_ids": [
      "TBL-000073"
    ]
  }
}
```

## Notes
