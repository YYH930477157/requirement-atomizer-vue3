---
id: KB-L3-IC-22-SINGLE-ACTION-SCHEDULE
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Single Action Schedule
aliases:
- COSEM Single Action Schedule
- Single action schedule object
- class 22
- CL 22
keywords:
- class 22
- cl 22
- single action schedule
- executed_script
- execution_time
- disconnect control scheduler
domain_tags:
- cosem_class
- schedule
- meter_function
---

# Single Action Schedule

## Definition

COSEM interface class for scheduling one or more script executions at defined times.

## Aliases

- COSEM Single Action Schedule
- Single action schedule object
- class 22
- CL 22

## Domain Tags

- `cosem_class`
- `schedule`
- `meter_function`

## Structured Data

```json metadata
{
  "class_id": 22,
  "version": 0,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 2,
      "name": "executed_script",
      "type": "structure {script_logical_name, script_selector}",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 3,
      "name": "type",
      "type": "enum",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 4,
      "name": "execution_time",
      "type": "array of execution_time_date",
      "mandatory": true,
      "storage": "static"
    }
  ],
  "methods": [],
  "access_semantics": [
    "executed_script references one Script table logical name and script selector.",
    "type defines whether execution_time contains one or many entries, whether dates allow wildcards, and whether time values may differ.",
    "execution_time stores time/date pairs; hundredths of seconds are zero for scheduled execution."
  ],
  "behavior_notes": [
    "Single action schedule models periodic action execution not necessarily linked to tariff calendars.",
    "The object delegates actual behavior to the referenced Script table action.",
    "Types 1 through 5 constrain the execution_time cardinality, wildcard use, and whether time values may vary."
  ],
  "common_instances": [
    {
      "name": "Disconnect control Scheduler",
      "obis": "0-0:15.0.1.255"
    },
    {
      "name": "Active end of billing period 1",
      "obis": "0-0:15.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.5.7 Single action schedule (class_id = 22, version = 0)"
    }
  ]
}
```

## Notes

