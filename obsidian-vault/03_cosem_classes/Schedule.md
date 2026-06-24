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
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "executed_script",
      "type": "script_definition",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "type",
      "type": "enum",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "execution_time",
      "type": "array",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "enable_disable"
    }
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
  ]
}
```

## Notes

