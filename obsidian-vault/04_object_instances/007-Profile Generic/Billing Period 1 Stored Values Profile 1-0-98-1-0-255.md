---
id: KB-OBIS-1-0-98-1-0-255-BILLING-PERIOD-1-STORED-VALUES-PROFILE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Date of billing period 1 Stored Billing Values Profile
aliases:
- Stored billing values profile period 1 1-0:98.1.0.255
- Billing period 1 stored values profile
keywords:
- 1-0:98.1.0.255
- Date of billing period 1 Stored Billing Values Profile
- billing period 1 stored values profile
- end of invoicing profile
domain_tags:
- cosem_object
- ac_electricity
- billing_profile
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# Date of billing period 1 Stored Billing Values Profile

## Definition

Row-level Profile generic object for AC stored billing values at the end of billing period 1, represented by OBIS `1-0:98.1.0.255`.

## Aliases

- Stored billing values profile period 1 1-0:98.1.0.255
- Billing period 1 stored values profile

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `billing_profile`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:98.1.0.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 aggregate channel",
    "C": "98 stored billing values profile objects",
    "D": "1 billing period 1",
    "E": "0 aggregate profile",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 24,
    "title": "OBIS codes for data profile objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 24 data profile objects - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Date of billing period 1 Stored Billing Values Profile at 1-0:98.1.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row for end-of-invoicing stored billing values captured in billing period 1.",
    "The Profile generic capture_objects define the concrete billing registers retained by this profile."
  ]
}
```

## Notes

