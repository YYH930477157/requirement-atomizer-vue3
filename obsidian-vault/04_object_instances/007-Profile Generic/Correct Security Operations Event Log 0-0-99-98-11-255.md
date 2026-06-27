---
id: KB-OBIS-0-0-99-98-11-255-CORRECT-SECURITY-OPERATIONS-EVENT-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Correct security operations event log
aliases:
- Correct security operations event log 0-0:99.98.11.255
- Successful security operations event log
keywords:
- 0-0:99.98.11.255
- correct security operations event log
- successful security operations event log
- security operations profile generic
domain_tags:
- cosem_object
- event
- profile_generic
- security_policy
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-12
---

# Correct security operations event log

## Definition

Row-level COSEM object instance for the Profile generic event log `0-0:99.98.11.255`, used to retain successful or correct security operation events.

## Aliases

- Correct security operations event log 0-0:99.98.11.255
- Successful security operations event log

## Domain Tags

- `cosem_object`
- `event`
- `profile_generic`
- `security_policy`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-12`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:99.98.11.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "99 data profile objects",
    "D": "98 event log",
    "E": "11 correct security operations",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 12,
    "title": "OBIS codes for data profile objects - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 12 data profile objects - Abstract"
    },
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.3.6 Profile generic common instances"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Correct security operations event log at 0-0:99.98.11.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements for retained successful security operation events.",
    "ABNT Appendix 9 configures this Profile generic with capture_objects including Clock, the related event object, and remote-client Security Setup."
  ]
}
```

## Notes

