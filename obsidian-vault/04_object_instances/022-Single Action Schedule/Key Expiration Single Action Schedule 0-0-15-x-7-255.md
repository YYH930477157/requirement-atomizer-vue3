---
id: KB-OBIS-0-0-15-X-7-255-KEY-EXPIRATION-SINGLE-ACTION-SCHEDULE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Key expiration Single action schedule
aliases:
- Key expiration Single action schedule 0-0:15.x.7.255
- Key expiration scheduler
keywords:
- 0-0:15.x.7.255
- Key expiration Single action schedule
- key expiration scheduler
- key reset schedule
domain_tags:
- cosem_object
- schedule
- security_policy
- key_management
relations:
- relation: instance_of
  target: KB-L3-IC-22-SINGLE-ACTION-SCHEDULE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Key expiration Single action schedule

## Definition

Pattern-level Single Action Schedule object for key-expiration and key-reset activation at OBIS `0-0:15.x.7.255`.

## Aliases

- Key expiration Single action schedule 0-0:15.x.7.255
- Key expiration scheduler

## Domain Tags

- `cosem_object`
- `schedule`
- `security_policy`
- `key_management`

## Relations

- `instance_of` -> `KB-L3-IC-22-SINGLE-ACTION-SCHEDULE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:15.x.7.255",
  "likely_interface_class_id": 22,
  "likely_interface_class_name": "Single Action Schedule",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "15 Single Action Schedule",
    "D": "x key client or context selector",
    "E": "7 key expiration action schedule",
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
      "source": "Blue Book Part 2 Ed. 16",
      "section": "Single Action Schedule interface class"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Key expiration Single action schedule at 0-0:15.x.7.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching scheduled key-expiration, key-reset, or secure-client key rollover requirements.",
    "ABNT Appendix 9 describes this schedule as selecting entries in the key expiration Script Table."
  ]
}
```

## Notes
