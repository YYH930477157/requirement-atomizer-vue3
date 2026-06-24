---
id: KB-L3-IC-71-LIMITER
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Limiter
aliases:
- Limiter object
- class 71
- CL 71
keywords:
- limiter
- class 71
- cl 71
- monitored_value
- threshold_active
- threshold_normal
- emergency_profile
- action_over_threshold
- action_under_threshold
- min_over_threshold_duration
- min_under_threshold_duration
domain_tags:
- cosem_class
- control
- event_control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Limiter

## Definition

COSEM interface class for monitoring a value against thresholds and invoking configured actions when over-threshold, under-threshold, or emergency profile conditions apply.

## Aliases

- Limiter object
- class 71
- CL 71

## Domain Tags

- `cosem_class`
- `control`
- `event_control`

## Structured Data

```json metadata
{
  "class_id": 71,
  "version": 0,
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "mandatory": true},
    {"attribute_id": 2, "name": "monitored_value", "type": "structure", "mandatory": true},
    {"attribute_id": 3, "name": "threshold_active", "type": "threshold", "mandatory": true, "storage": "dynamic"},
    {"attribute_id": 4, "name": "threshold_normal", "type": "threshold", "mandatory": true, "storage": "static"},
    {"attribute_id": 5, "name": "threshold_emergency", "type": "threshold", "mandatory": true, "storage": "static"},
    {"attribute_id": 6, "name": "min_over_threshold_duration", "type": "double-long-unsigned", "mandatory": true},
    {"attribute_id": 7, "name": "min_under_threshold_duration", "type": "double-long-unsigned", "mandatory": true},
    {"attribute_id": 8, "name": "emergency_profile", "type": "structure", "mandatory": true},
    {"attribute_id": 9, "name": "emergency_profile_group_id_list", "type": "array", "mandatory": true},
    {"attribute_id": 10, "name": "emergency_profile_active", "type": "boolean", "mandatory": true},
    {"attribute_id": 11, "name": "actions", "type": "structure", "mandatory": true}
  ],
  "methods": [],
  "behavior_notes": [
    "monitored_value identifies the object attribute monitored by the limiter and only simple data types are allowed.",
    "threshold_active follows threshold_normal or threshold_emergency depending on whether an emergency profile is active.",
    "over-threshold and under-threshold actions are executed only after the configured minimum duration is exceeded."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.5.9 Limiter (class_id = 71, version = 0)"
    }
  ]
}
```

## Notes
