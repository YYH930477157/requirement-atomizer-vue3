---
id: KB-OBIS-0-B-99-98-E-ABSTRACT-EVENT-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Abstract event log profile
aliases:
- Event log profile 0-b:99.98.e
- Abstract OBIS event log
keywords:
- 0-b:99.98.e
- abstract event log profile
- event log profile
- Profile generic event log
domain_tags:
- cosem_object
- event
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-12
---

# Abstract event log profile

## Definition

Pattern-level row entry for abstract event log Profile generic objects using OBIS pattern `0-b:99.98.e`.

## Aliases

- Event log profile 0-b:99.98.e
- Abstract OBIS event log

## Domain Tags

- `cosem_object`
- `event`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-12`

## Structured Data

```json metadata
{
  "obis_pattern": "0-b:99.98.e",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "b channel or logical-device selector",
    "C": "99 data profile objects",
    "D": "98 event log",
    "E": "e profile selector",
    "F": "not used in this table row"
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
    }
  ],
  "applicable_notes": [
    "Use the abstract event log profile pattern when a log also holds data not specific to an energy type.",
    "Concrete media-specific event logs refine this pattern with A=1 for AC or A=2 for DC."
  ]
}
```

## Notes

