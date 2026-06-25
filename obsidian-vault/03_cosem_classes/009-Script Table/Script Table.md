---
id: KB-L3-IC-9-SCRIPT-TABLE
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Script Table
aliases:
- class 9
- CL 9
keywords:
- class 9
- cl 9
- script table
- script_identifier
- script_actions
- tariffication script table
domain_tags:
- cosem_class
- script
- meter_function
---

# Script Table

## Definition

COSEM class containing executable scripts, each composed of action specifications.

## Aliases

- class 9
- CL 9

## Domain Tags

- `cosem_class`
- `script`
- `meter_function`

## Structured Data

```json metadata
{
  "class_id": 9,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "scripts",
      "type": "array",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "execute",
      "parameter_type": "long-unsigned"
    }
  ]
}
```

## Notes

