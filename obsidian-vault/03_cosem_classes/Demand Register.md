---
id: KB-L3-IC-5-DEMAND-REGISTER
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Demand Register
aliases:
- COSEM Demand Register
- class 5
- CL 5
keywords:
- class 5
- cl 5
- demand register
- current_average_value
- last_average_value
- capture_time
- next_period
- number_of_periods
domain_tags:
- cosem_class
- demand_register
- measurement_data
---

# Demand Register

## Definition

COSEM interface class for demand values based on averaging periods.

## Aliases

- COSEM Demand Register
- class 5
- CL 5

## Domain Tags

- `cosem_class`
- `demand_register`
- `measurement_data`

## Structured Data

```json metadata
{
  "class_id": 5,
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
      "name": "current_average_value",
      "type": "CHOICE",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 3,
      "name": "last_average_value",
      "type": "CHOICE",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 4,
      "name": "scaler_unit",
      "type": "scal_unit_type",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 5,
      "name": "status",
      "type": "CHOICE",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 6,
      "name": "capture_time",
      "type": "octet-string",
      "mandatory": true,
      "storage": "dynamic",
      "format": "date-time"
    },
    {
      "attribute_id": 7,
      "name": "start_time_current",
      "type": "octet-string",
      "mandatory": true,
      "storage": "dynamic",
      "format": "date-time"
    },
    {
      "attribute_id": 8,
      "name": "period",
      "type": "double-long-unsigned",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 9,
      "name": "number_of_periods",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "parameter_type": "integer(0)"
    },
    {
      "method_id": 2,
      "name": "next_period",
      "parameter_type": "integer(0)"
    }
  ],
  "behavior_notes": [
    "current_average_value is the running demand over the current averaging interval.",
    "last_average_value is calculated over the previous number_of_periods multiplied by period interval.",
    "period and number_of_periods define the demand calculation interval."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.3.4 Demand register (class_id = 5, version = 0)"
    }
  ]
}
```

## Notes

