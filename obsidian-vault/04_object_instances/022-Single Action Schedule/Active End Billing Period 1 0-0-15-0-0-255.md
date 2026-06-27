---
id: KB-OBIS-0-0-15-0-0-255-ACTIVE-END-BILLING-PERIOD-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active end of billing period 1
aliases:
- Active end of billing period 1 0-0:15.0.0.255
- Billing period 1 single action schedule
keywords:
- 0-0:15.0.0.255
- Active end of billing period 1
- end of billing period 1 schedule
- billing period single action schedule
domain_tags:
- cosem_object
- schedule
- billing_period
- demand_reset
relations:
- relation: instance_of
  target: KB-L3-IC-22-SINGLE-ACTION-SCHEDULE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Active end of billing period 1

## Definition

Row-level Single Action Schedule object for active end-of-billing-period 1 execution at logical name `0-0:15.0.0.255`.

## Aliases

- Active end of billing period 1 0-0:15.0.0.255
- Billing period 1 single action schedule

## Domain Tags

- `cosem_object`
- `schedule`
- `billing_period`
- `demand_reset`

## Relations

- `instance_of` -> `KB-L3-IC-22-SINGLE-ACTION-SCHEDULE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:15.0.0.255",
  "likely_interface_class_id": 22,
  "likely_interface_class_name": "Single Action Schedule",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "15 Single Action Schedule",
    "D": "0 predefined schedule group",
    "E": "0 active billing period 1 schedule",
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
      "section": "Active end of billing period 1 at 0-0:15.0.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching billing-period closing schedules for period 1.",
    "The schedule executes a Script Table action through executed_script and execution_time."
  ]
}
```

## Notes
