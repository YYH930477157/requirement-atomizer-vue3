---
id: KB-L3-IC-6-REGISTER-ACTIVATION
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Register Activation
aliases:
- class 6
- CL 6
keywords:
- class 6
- cl 6
- register activation
- active_mask
- register_assignment
domain_tags:
- cosem_class
- billing_profile
- tariff_calendar
---

# Register Activation

## Definition

COSEM class used to define active register masks and register assignments.

## Aliases

- class 6
- CL 6

## Domain Tags

- `cosem_class`
- `billing_profile`
- `tariff_calendar`

## Structured Data

```json metadata
{
  "class_id": 6,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "register_assignment",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "mask_list",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "active_mask",
      "type": "octet-string",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "add_register"
    },
    {
      "method_id": 2,
      "name": "add_mask"
    },
    {
      "method_id": 3,
      "name": "delete_mask"
    }
  ]
}
```

## Notes

