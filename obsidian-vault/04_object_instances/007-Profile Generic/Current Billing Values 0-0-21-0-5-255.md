---
id: KB-OBIS-0-0-21-0-5-255-CURRENT-BILLING-VALUES
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Current billing values
aliases:
- Current billing values profile 0-0:21.0.5.255
- Billing values current
keywords:
- 0-0:21.0.5.255
- Current billing values
- billing values current
- current billing values profile
domain_tags:
- cosem_object
- billing_profile
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-12
---

# Current billing values

## Definition

Row-level abstract Profile generic object for current billing values, represented by OBIS `0-0:21.0.5.255`.

## Aliases

- Current billing values profile 0-0:21.0.5.255
- Billing values current

## Domain Tags

- `cosem_object`
- `billing_profile`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-12`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:21.0.5.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "21 current billing value profile group",
    "D": "0 aggregate channel",
    "E": "5 current billing values",
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
      "source": "ABNT Appendix 9 extracted table",
      "section": "Current billing values at 0-0:21.0.5.255"
    }
  ],
  "applicable_notes": [
    "Use this row when current billing values are represented as a Profile generic object.",
    "ABNT Appendix 9 describes this object as the current billing values profile."
  ]
}
```

## Notes

