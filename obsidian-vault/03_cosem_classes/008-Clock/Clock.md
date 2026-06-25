---
id: KB-L3-IC-8-CLOCK
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Clock
aliases:
- COSEM Clock
- class 8
- CL 8
keywords:
- class 8
- cl 8
- clock
- time_zone
- daylight_savings
- clock_base
domain_tags:
- cosem_class
- clock
- meter_function
---

# Clock

## Definition

COSEM interface class for date, time, timezone, daylight saving, and clock status.

## Aliases

- COSEM Clock
- class 8
- CL 8

## Domain Tags

- `cosem_class`
- `clock`
- `meter_function`

## Structured Data

```json metadata
{
  "class_id": 8,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "time",
      "type": "date_time",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "time_zone",
      "type": "long",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "status",
      "type": "unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "daylight_savings_begin",
      "type": "date_time",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "daylight_savings_end",
      "type": "date_time",
      "mandatory": true
    },
    {
      "attribute_id": 7,
      "name": "daylight_savings_deviation",
      "type": "integer",
      "mandatory": true
    },
    {
      "attribute_id": 8,
      "name": "daylight_savings_enabled",
      "type": "boolean",
      "mandatory": true
    },
    {
      "attribute_id": 9,
      "name": "clock_base",
      "type": "enum",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "adjust_to_quarter"
    },
    {
      "method_id": 2,
      "name": "adjust_to_measuring_period"
    },
    {
      "method_id": 3,
      "name": "adjust_to_minute"
    },
    {
      "method_id": 4,
      "name": "adjust_to_preset_time"
    },
    {
      "method_id": 5,
      "name": "preset_adjusting_time"
    },
    {
      "method_id": 6,
      "name": "shift_time"
    }
  ],
  "common_instances": [
    {
      "name": "Clock",
      "obis": "0-0:1.0.0.255"
    }
  ]
}
```

## Notes

