---
id: KB-L3-IC-65-PARAMETER-MONITOR
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Parameter monitor
aliases:
- class 65
- CL 65
keywords:
- parameter monitor
- class 65
- cl 65
domain_tags:
- cosem_class
- control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Parameter monitor

## Definition

COSEM interface class for monitoring or controlling device behavior through Parameter monitor functions.

## Aliases

- class 65
- CL 65

## Domain Tags

- `cosem_class`
- `control`

## Structured Data

```json metadata
{
  "class_id": 65,
  "version": 1,
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
      "name": "changed_parameter",
      "type": "structure",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 3,
      "name": "capture_time",
      "type": "date-time",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 4,
      "name": "parameter_list",
      "type": "array",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 5,
      "name": "parameter_list_name",
      "type": "octet-string",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 6,
      "name": "hash_algorithm_id",
      "type": "enum",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 7,
      "name": "parameter_value_digest",
      "type": "octet-string",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 8,
      "name": "parameter_values",
      "type": "structure",
      "mandatory": true,
      "storage": "dynamic"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "add_parameter",
      "parameter_type": "parameter_list_element",
      "meaning": "Add one parameter reference to parameter_list."
    },
    {
      "method_id": 2,
      "name": "delete_parameter",
      "parameter_type": "parameter_list_element",
      "meaning": "Delete one parameter reference from parameter_list."
    }
  ],
  "access_semantics": [
    "parameter_list defines the monitored class_id, logical_name, and attribute_index references.",
    "changed_parameter and capture_time report the most recent change.",
    "parameter_value_digest lets clients compare a known configuration snapshot before reading parameter_values."
  ],
  "behavior_notes": [
    "Parameter monitor supports configuration-change detection for a defined list of COSEM attributes.",
    "The digest is calculated over parameter values in parameter_list order using hash_algorithm_id.",
    "parameter_values holds A-XDR encoded copies of referenced attributes and may be captured into Profile generic buffers."
  ],
  "common_instances": [
    {
      "name": "Configuration parameter monitor",
      "obis": "implementation-specific"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.5.10 Parameter monitor (class_id = 65, version = 1)"
    }
  ]
}
```

## Notes
