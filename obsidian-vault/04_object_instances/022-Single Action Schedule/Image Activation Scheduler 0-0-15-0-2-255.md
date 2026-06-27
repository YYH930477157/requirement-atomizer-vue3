---
id: KB-OBIS-0-0-15-0-2-255-IMAGE-ACTIVATION-SCHEDULER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Image Activation Scheduler
aliases:
- Image Activation Scheduler 0-0:15.0.2.255
- Firmware image activation scheduler
keywords:
- 0-0:15.0.2.255
- Image Activation Scheduler
- firmware image activation scheduler
- activate new firmware
domain_tags:
- cosem_object
- schedule
- firmware
- image_transfer
relations:
- relation: instance_of
  target: KB-L3-IC-22-SINGLE-ACTION-SCHEDULE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Image Activation Scheduler

## Definition

Row-level Single Action Schedule object that schedules image activation at logical name `0-0:15.0.2.255`.

## Aliases

- Image Activation Scheduler 0-0:15.0.2.255
- Firmware image activation scheduler

## Domain Tags

- `cosem_object`
- `schedule`
- `firmware`
- `image_transfer`

## Relations

- `instance_of` -> `KB-L3-IC-22-SINGLE-ACTION-SCHEDULE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:15.0.2.255",
  "likely_interface_class_id": 22,
  "likely_interface_class_name": "Single Action Schedule",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "15 Single Action Schedule",
    "D": "0 predefined schedule group",
    "E": "2 image activation scheduler",
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
      "section": "Image Activation Scheduler at 0-0:15.0.2.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching scheduled firmware activation requirements.",
    "ABNT Appendix 9 describes this object as activating new firmware through a scheduled script reference."
  ]
}
```

## Notes
