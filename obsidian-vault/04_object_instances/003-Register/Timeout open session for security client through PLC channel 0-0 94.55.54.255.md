---
id: KB-ABNT-OBIS-0-0-94-55-54-255-TIMEOUT-OPEN-SESSION-FOR-SECURITY-CLIENT-THROUGH-PLC-CHANNEL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Timeout open session for security client through PLC channel
aliases:
- OBIS 0-0:94.55.54.255
keywords:
- 0-0:94.55.54.255
- Timeout open session for security client through PLC channel
- TBL-000073
domain_tags:
- cosem_object
- general
- communication_profile
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Timeout open session for security client through PLC channel

## Definition

Row-level Register object at logical name `0-0:94.55.54.255`. Timeout for an open session of a security client over the PLC channel

## Aliases

- OBIS 0-0:94.55.54.255

## Domain Tags

- `cosem_object`
- `general`
- `communication_profile`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:94.55.54.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "54 security-client PLC session timeout",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 9,
    "title": "OBIS codes for error registers, alarm registers and alarm filters - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 9 OBIS codes for error registers, alarm registers and alarm filters - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Timeout open session for security client through PLC channel at 0-0:94.55.54.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about timeout for an open session of a security client over the plc channel.",
    "ABNT Appendix 9 describes this object as: timeout for an open session of a security client over the PLC channel."
  ]
}
```

## Notes
