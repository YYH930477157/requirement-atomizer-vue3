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
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "current_average_value",
      "type": "choice",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "last_average_value",
      "type": "choice",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "scaler_unit",
      "type": "scal_unit_type",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "status",
      "type": "choice",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "capture_time",
      "type": "date_time",
      "mandatory": true
    },
    {
      "attribute_id": 7,
      "name": "start_time_current",
      "type": "date_time",
      "mandatory": true
    },
    {
      "attribute_id": 8,
      "name": "period",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 9,
      "name": "number_of_periods",
      "type": "long-unsigned",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "parameter_type": "integer(0)"
    }
  ]
}
```

## Notes

