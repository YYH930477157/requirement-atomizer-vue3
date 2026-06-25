---
id: KB-L3-IC-10-SCHEDULE
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Schedule
aliases:
- COSEM Schedule
- class 10
- CL 10
keywords:
- schedule
- class 10
- cl 10
- entries
- script logical name
- script selector
domain_tags:
- cosem_class
- schedule
- control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Schedule

## Definition

COSEM interface class for schedule tables that define scripts to be executed according to configured times or calendar conditions.

## Aliases

- COSEM Schedule
- class 10
- CL 10

## Domain Tags

- `cosem_class`
- `schedule`
- `control`

## Structured Data

```json metadata
{
  "class_id": 10,
  "version": 0,
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "mandatory": true, "storage": "static"},
    {"attribute_id": 2, "name": "entries", "type": "array of schedule_table_entry", "mandatory": true, "storage": "static"}
  ],
  "methods": [
    {"method_id": 1, "name": "enable_disable", "parameter_type": "structure {firstIndexA, lastIndexA, firstIndexB, lastIndexB}", "meaning": "Disable range A and enable range B."},
    {"method_id": 2, "name": "insert", "parameter_type": "schedule_table_entry", "meaning": "Insert or overwrite one schedule entry by index."},
    {"method_id": 3, "name": "delete", "parameter_type": "structure {firstIndex, lastIndex}", "meaning": "Delete a range of schedule entries."}
  ],
  "access_semantics": [
    "entries is static configuration containing script logical names, script selectors, switch time, validity window, weekday masks, special-day masks, and begin/end dates.",
    "enable_disable, insert, and delete modify schedule execution state or table contents through action methods.",
    "A Schedule entry executes at most one script; multiple scripts at the same instant are ordered by entry index."
  ],
  "behavior_notes": [
    "Schedule works with Special days table to model time- and date-driven device activities.",
    "After power failure, missed entries are processed in order when they are still within their validity_window.",
    "Forward time changes are handled like power failure recovery; backward time changes can repeat entries during the repeated interval.",
    "Time synchronization shall avoid losing entries or executing entries twice; daylight-saving forward intervals execute missed scripts and backward intervals suppress re-execution."
  ],
  "common_instances": [],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.5.3 Schedule (class_id = 10, version = 0)"
    }
  ]
}
```

## Notes

