---
id: KB-ABNT-OBIS-0-0-43-1-5-255-SECURITY-INVOCATION-COUNTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Security-Invocation counter
aliases:
- OBIS 0-0:43.1.5.255
- Summon Counter in reception - "unicast" key (remote)
keywords:
- 0-0:43.1.5.255
- Security-Invocation counter
- security invocation counter
- unicast key remote
- TBL-000036
domain_tags:
- cosem_object
- general
- security
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Security-Invocation counter

## Definition

Row-level Data object holding the security invocation (summon) counter for the remote unicast key at logical name `0-0:43.1.5.255`.

## Aliases

- OBIS 0-0:43.1.5.255
- Summon Counter in reception - "unicast" key (remote)

## Domain Tags

- `cosem_object`
- `general`
- `security`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:43.1.5.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "43 security management",
    "D": "1 security setup/invocation",
    "E": "5 invocation counter (remote unicast key, per ABNT)",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Security-Invocation counter at 0-0:43.1.5.255 (Summon Counter in reception - unicast key, remote)"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about per-key security invocation / replay counters for the remote unicast key.",
    "ABNT Appendix 9 describes this object as the summon counter in reception for the remote unicast key."
  ]
}
```

## Notes
