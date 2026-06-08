---
id: KB-L3-IC-1-DATA
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Data
aliases:
- COSEM Data
- class 1
- CL 1
keywords:
- class 1
- cl 1
- data object
- cosem logical device name
- device id
- security-invocation counter
domain_tags:
- cosem_class
- cosem_object
- data_model
---

# Data

## Definition

Generic COSEM interface class for a single data value.

## Aliases

- COSEM Data
- class 1
- CL 1

## Domain Tags

- `cosem_class`
- `cosem_object`
- `data_model`

## Structured Data

```json metadata
{
  "class_id": 1,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "meaning": "OBIS logical name of the object"
    },
    {
      "attribute_id": 2,
      "name": "value",
      "type": "any",
      "mandatory": true,
      "meaning": "Stored data value"
    }
  ],
  "methods": [],
  "common_instances": [
    {
      "name": "COSEM logical device name",
      "obis": "0-0:42.0.0.255"
    },
    {
      "name": "Device ID 1",
      "obis": "0-0:96.1.0.255"
    },
    {
      "name": "Device ID 5",
      "obis": "0-0:96.1.4.255"
    },
    {
      "name": "Security-Invocation counter",
      "obis_pattern": "0-0:43.1.x.255"
    }
  ]
}
```

## Notes

