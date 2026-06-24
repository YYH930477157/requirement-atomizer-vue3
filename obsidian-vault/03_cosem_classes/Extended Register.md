---
id: KB-L3-IC-4-EXTENDED-REGISTER
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Extended Register
aliases:
- COSEM Extended Register
- class 4
- CL 4
keywords:
- class 4
- cl 4
- extended register
- capture_time
- status
- scaler_unit
- reset
domain_tags:
- cosem_class
- register
- measurement_data
---

# Extended Register

## Definition

COSEM register with status and capture time in addition to value and scaler/unit.

## Aliases

- COSEM Extended Register
- class 4
- CL 4

## Domain Tags

- `cosem_class`
- `register`
- `measurement_data`

## Structured Data

```json metadata
{
  "class_id": 4,
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
      "name": "value",
      "type": "CHOICE",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 3,
      "name": "scaler_unit",
      "type": "scal_unit_type",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 4,
      "name": "status",
      "type": "CHOICE",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 5,
      "name": "capture_time",
      "type": "octet-string",
      "mandatory": true,
      "storage": "dynamic",
      "format": "date-time"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "parameter_type": "integer(0)"
    }
  ],
  "behavior_notes": [
    "Extends Register with status and capture_time so the value can be qualified by status and capture timestamp.",
    "reset sets value to the instance-specific default and sets capture_time to the reset execution time."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.3.3 Extended register (class_id = 4, version = 0)"
    }
  ]
}
```

## Notes

