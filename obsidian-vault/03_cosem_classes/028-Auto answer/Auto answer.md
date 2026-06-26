---
id: KB-L3-IC-28-AUTO-ANSWER
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Auto answer
aliases:
- class 28
- CL 28
keywords:
- auto answer
- listening window
- number of rings
- auto answer mode
- incoming call
- class 28
- cl 28
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Auto answer

## Definition

COSEM interface class for controlling how a device answers incoming communication calls.

## Aliases

- class 28
- CL 28

## Domain Tags

- `cosem_class`

## Structured Data

```json metadata
{
  "class_id": 28,
  "version": 2,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "meaning": "OBIS logical name of the auto answer object"
    },
    {
      "attribute_id": 2,
      "name": "mode",
      "type": "enum",
      "mandatory": true,
      "meaning": "Auto-answer operating mode"
    },
    {
      "attribute_id": 3,
      "name": "listening_window",
      "type": "array",
      "mandatory": true,
      "meaning": "Time windows during which the device is allowed to answer incoming calls"
    },
    {
      "attribute_id": 4,
      "name": "status",
      "type": "enum",
      "mandatory": true,
      "meaning": "Current auto-answer status"
    },
    {
      "attribute_id": 5,
      "name": "number_of_calls",
      "type": "long-unsigned",
      "mandatory": false,
      "meaning": "Number of answered incoming calls or calls tracked by the auto-answer function"
    },
    {
      "attribute_id": 6,
      "name": "number_of_rings",
      "type": "long-unsigned",
      "mandatory": false,
      "meaning": "Number of rings before the device answers"
    }
  ],
  "methods": [],
  "access_semantics": [
    "The auto answer object determines whether and when the meter accepts incoming communication sessions.",
    "Listening-window configuration is time-dependent behavior and should be validated with clock/time-zone assumptions.",
    "Ring and call counters support diagnostics but should not be confused with metering event logs."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.28 Auto answer (class_id = 28, version = 2)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with incoming-call mode, listening-window, status, calls, and ring semantics."
}
```

## Notes

- Use this class when requirements mention incoming calls, scheduled answer windows, or ring-count behavior.
