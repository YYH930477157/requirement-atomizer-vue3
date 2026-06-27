---
id: KB-OBIS-0-1-94-55-116-255-CORRECT-SECURITY-OPERATIONS-EVENT-LOG-FILTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Correct security operations event log filter
aliases:
- Correct security operations event log filter 0-1:94.55.116.255
- Correct security event filter
keywords:
- 0-1:94.55.116.255
- Correct security operations event log filter
- correct security event filter
- successful security operations filter
domain_tags:
- cosem_object
- event
- security_policy
- data_model
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Correct security operations event log filter

## Definition

Row-level Data object for the filter value applied to correct security operations event logging, specialized to logical name `0-1:94.55.116.255`.

## Aliases

- Correct security operations event log filter 0-1:94.55.116.255
- Correct security event filter

## Domain Tags

- `cosem_object`
- `event`
- `security_policy`
- `data_model`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-1:94.55.116.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 channel or client-specific selector",
    "C": "94 extended data objects",
    "D": "55 event filter group",
    "E": "116 correct security operations event log filter",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 9,
    "title": "OBIS codes for data objects - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 9 data objects - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Correct security operations event log filter at 0-1:94.55.116.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching bit-string filters that select which correct security operation events are retained or notified.",
    "ABNT Appendix 9 models this filter as a Data object with an array of bit-string values."
  ]
}
```

## Notes

