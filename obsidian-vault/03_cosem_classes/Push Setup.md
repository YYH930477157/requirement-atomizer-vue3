---
id: KB-L3-IC-40-PUSH-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Push Setup
aliases:
- Push setup object
- class 40
- CL 40
keywords:
- push setup
- class 40
- cl 40
- push_object_list
- send_destination_and_method
- communication_window
- randomisation_start_interval
- number_of_retries
- repetition_delay
- push_protection_parameters
- push_operation_method
- confirmation_parameters
- last_confirmation_date_time
domain_tags:
- cosem_class
- communication_profile
- push
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Push Setup

## Definition

COSEM interface class for configuring push operations, including the objects to push, destination and transport method, communication windows, retry behavior, and repetition delay.

## Aliases

- Push setup object
- class 40
- CL 40

## Domain Tags

- `cosem_class`
- `communication_profile`
- `push`

## Structured Data

```json metadata
{
  "class_id": 40,
  "version": 3,
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "mandatory": true},
    {"attribute_id": 2, "name": "push_object_list", "type": "array", "mandatory": true},
    {"attribute_id": 3, "name": "send_destination_and_method", "type": "structure", "mandatory": true},
    {"attribute_id": 4, "name": "communication_window", "type": "array", "mandatory": true},
    {"attribute_id": 5, "name": "randomisation_start_interval", "type": "long-unsigned", "mandatory": true},
    {"attribute_id": 6, "name": "number_of_retries", "type": "unsigned", "mandatory": true},
    {"attribute_id": 7, "name": "repetition_delay", "type": "structure", "mandatory": true},
    {"attribute_id": 8, "name": "port_reference", "type": "octet-string", "mandatory": true},
    {"attribute_id": 9, "name": "push_client_SAP", "type": "integer", "mandatory": true},
    {"attribute_id": 10, "name": "push_protection_parameters", "type": "array", "mandatory": true},
    {"attribute_id": 11, "name": "push_operation_method", "type": "enum", "mandatory": true},
    {"attribute_id": 12, "name": "confirmation_parameters", "type": "structure", "mandatory": true},
    {"attribute_id": 13, "name": "last_confirmation_date_time", "type": "date-time", "mandatory": true, "storage": "dynamic"}
  ],
  "methods": [
    {"method_id": 1, "name": "push", "mandatory": true},
    {"method_id": 2, "name": "reset", "mandatory": false}
  ],
  "behavior_notes": [
    "push_object_list defines the COSEM object attributes sent when push is invoked.",
    "Push is sent using the DataNotification service when configured trigger conditions are met.",
    "communication_window, randomisation_start_interval, number_of_retries, and repetition_delay define delayed execution and retry behavior.",
    "push_protection_parameters define data protection options for pushed data."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.8.2 Push setup (class_id = 40, version = 3)"
    }
  ]
}
```

## Notes
