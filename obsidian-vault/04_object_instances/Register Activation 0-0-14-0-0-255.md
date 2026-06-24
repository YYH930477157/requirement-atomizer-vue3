---
id: KB-OBIS-0-0-14-0-0-255-REGISTER-ACTIVATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Register activation
aliases:
- Register activation 0-0:14.0.0.255
- tariff register activation
keywords:
- 0-0:14.0.0.255
- Register activation
- active_mask
- mask_list
- register_assignment
domain_tags:
- cosem_object
- tariff_calendar
- billing_profile
relations:
- relation: instance_of
  target: KB-L3-IC-6-REGISTER-ACTIVATION
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Register activation

## Definition

Row-level COSEM object instance for Register activation logical name `0-0:14.0.0.255`, used to select active register masks for tariff structures.

## Aliases

- Register activation 0-0:14.0.0.255
- tariff register activation

## Domain Tags

- `cosem_object`
- `tariff_calendar`
- `billing_profile`

## Relations

- `instance_of` -> `KB-L3-IC-6-REGISTER-ACTIVATION`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:14.0.0.255",
  "likely_interface_class_id": 6,
  "likely_interface_class_name": "Register Activation",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "14 register activation",
    "D": "0 default instance",
    "E": "0 default instance",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.3.5 Register activation (class_id = 6)"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Register activation row"
    }
  ],
  "applicable_notes": [
    "ABNT Appendix 9 uses this object with class_id 6 and value 0-0:14.0.0.255.",
    "Use this instance for active_mask, mask_list, register_assignment, and tariff activation requirements."
  ]
}
```

## Notes
