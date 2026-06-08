---
id: KB-L3-IC-7-PROFILE-GENERIC
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Profile Generic
aliases:
- COSEM Profile Generic
- class 7
- CL 7
keywords:
- class 7
- cl 7
- profile generic
- capture_objects
- buffer
- capture_period
- profile_entries
- sort_method
domain_tags:
- cosem_class
- profile_generic
- measurement_data
- log
---

# Profile Generic

## Definition

COSEM interface class for storing captured entries such as load profiles, billing profiles, event logs, and alarm/error logs.

## Aliases

- COSEM Profile Generic
- class 7
- CL 7

## Domain Tags

- `cosem_class`
- `profile_generic`
- `measurement_data`
- `log`

## Structured Data

```json metadata
{
  "class_id": 7,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "buffer",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "capture_objects",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "capture_period",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "sort_method",
      "type": "enum",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "sort_object",
      "type": "capture_object_definition",
      "mandatory": true
    },
    {
      "attribute_id": 7,
      "name": "entries_in_use",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 8,
      "name": "profile_entries",
      "type": "double-long-unsigned",
      "mandatory": true
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
      "name": "capture",
      "parameter_type": "integer(0)"
    }
  ],
  "common_instances": [
    {
      "name": "Correct security operations event log",
      "obis": "0-0:99.98.11.255"
    },
    {
      "name": "Failed security operations event log",
      "obis": "0-0:99.98.12.255"
    }
  ]
}
```

## Notes

