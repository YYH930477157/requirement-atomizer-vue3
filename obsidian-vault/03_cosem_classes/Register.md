---
id: KB-L3-IC-3-REGISTER
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Register
aliases:
- COSEM Register
- class 3
- CL 3
keywords:
- class 3
- cl 3
- register
- scaler_unit
- threshold
- duration of
domain_tags:
- cosem_class
- register
- measurement_data
---

# Register

## Definition

COSEM interface class for a measured value with scaler and unit.

## Aliases

- COSEM Register
- class 3
- CL 3

## Domain Tags

- `cosem_class`
- `register`
- `measurement_data`

## Structured Data

```json metadata
{
  "class_id": 3,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "value",
      "type": "choice",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "scaler_unit",
      "type": "scal_unit_type",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "parameter_type": "integer(0)",
      "meaning": "Reset register value when supported"
    }
  ],
  "common_instances": [
    {
      "name": "Time threshold for long power failure",
      "obis": "0-0:96.7.20.255"
    },
    {
      "name": "Threshold for long power failure",
      "obis": "0-0:94.55.60.255"
    }
  ]
}
```

## Notes

