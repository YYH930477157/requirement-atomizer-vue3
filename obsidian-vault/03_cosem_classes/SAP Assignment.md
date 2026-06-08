---
id: KB-L3-IC-17-SAP-ASSIGNMENT
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: SAP Assignment
aliases:
- class 17
- CL 17
keywords:
- class 17
- cl 17
- sap assignment
- sap_assignment_list
domain_tags:
- cosem_class
- association
- logical_device
---

# SAP Assignment

## Definition

COSEM interface class listing SAP assignments for logical devices.

## Aliases

- class 17
- CL 17

## Domain Tags

- `cosem_class`
- `association`
- `logical_device`

## Structured Data

```json metadata
{
  "class_id": 17,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "SAP_assignment_list",
      "type": "array",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "connect_logical_device"
    },
    {
      "method_id": 2,
      "name": "disconnect_logical_device"
    }
  ],
  "common_instances": [
    {
      "name": "SAP Assignment",
      "obis": "0-0:41.0.0.255"
    }
  ]
}
```

## Notes

