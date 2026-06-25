---
id: KB-L3-IC-21-REGISTER-MONITOR
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Register monitor
aliases:
- class 21
- CL 21
keywords:
- register monitor
- class 21
- cl 21
domain_tags:
- cosem_class
- measurement_data
- control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Register monitor

## Definition

COSEM interface class for monitoring or controlling device behavior through Register monitor functions.

## Aliases

- class 21
- CL 21

## Domain Tags

- `cosem_class`
- `measurement_data`
- `control`

## Structured Data

```json metadata
{
  "class_id": 21,
  "version": 0,
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
      "name": "thresholds",
      "type": "array",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 3,
      "name": "monitored_value",
      "type": "value_definition",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 4,
      "name": "actions",
      "type": "array of action_set",
      "mandatory": true,
      "storage": "static"
    }
  ],
  "methods": [],
  "access_semantics": [
    "thresholds, monitored_value, and actions are static configuration for threshold crossing behavior.",
    "monitored_value references a simple typed attribute of Data, Register, Extended register, or Demand register.",
    "actions has the same number of elements as thresholds; each action_set maps upward and downward threshold crossings to Script table actions."
  ],
  "behavior_notes": [
    "Register monitor executes scripts when the referenced value crosses configured thresholds.",
    "The object requires a Script table instance in the same logical device.",
    "Threshold values use the same type as the monitored attribute."
  ],
  "common_instances": [
    {
      "name": "Event monitor",
      "obis": "implementation-specific"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.5.6 Register monitor (class_id = 21, version = 0)"
    }
  ]
}
```

## Notes
