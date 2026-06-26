---
id: KB-L3-IC-77-M-BUS-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: M-Bus diagnostic
aliases:
- class 77
- CL 77
- m-bus diagnostics
- m-bus diagnostic counters
keywords:
- m-bus diagnostic
- class 77
- cl 77
- m-bus counter
- m-bus error counter
- m-bus communication status
- diagnostic counter
domain_tags:
- cosem_class
- communication_profile
- m_bus
- diagnostics
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# M-Bus diagnostic

## Definition

COSEM interface class for exposing M-Bus diagnostic status, error counters, and communication health information.

## Aliases

- class 77
- CL 77
- m-bus diagnostics
- m-bus diagnostic counters

## Domain Tags

- `cosem_class`
- `communication_profile`
- `m_bus`
- `diagnostics`

## Structured Data

```json metadata
{
  "class_id": 77,
  "version": 0,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "access": "R",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "received_frames_counter",
      "type": "double-long-unsigned",
      "access": "R",
      "mandatory": true,
      "meaning": "Counter for M-Bus frames received by the diagnostic object"
    },
    {
      "attribute_id": 3,
      "name": "transmitted_frames_counter",
      "type": "double-long-unsigned",
      "access": "R",
      "mandatory": true,
      "meaning": "Counter for M-Bus frames transmitted by the diagnostic object"
    },
    {
      "attribute_id": 4,
      "name": "error_counter",
      "type": "double-long-unsigned",
      "access": "R",
      "mandatory": true,
      "meaning": "Counter for detected M-Bus communication errors"
    },
    {
      "attribute_id": 5,
      "name": "last_communication_status",
      "type": "enum",
      "access": "R",
      "mandatory": false,
      "meaning": "Last known M-Bus communication status or failure reason"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "mandatory": false,
      "meaning": "Reset diagnostic counters when supported by the implementation"
    }
  ],
  "access_semantics": [
    "Diagnostic counters are read-only operational evidence used for maintenance, installation, and troubleshooting.",
    "Counter reset is an active maintenance operation and should be restricted or audited.",
    "Diagnostic status should be correlated with M-Bus client and port setup requirements before deriving implementation defects."
  ],
  "behavior_notes": [
    "Use this class when requirements mention M-Bus error counters, communication diagnostics, received/transmitted frame counts, or resetting diagnostics.",
    "Diagnostics requirements should not be merged with ordinary measurement capture requirements; they describe communication health."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.40 M-Bus diagnostic (class_id = 77, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with diagnostic counters, communication status, reset operation, and troubleshooting semantics."
}
```

## Notes

- Use this object to anchor M-Bus communication health and maintenance requirements.
