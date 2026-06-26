---
id: KB-L3-IC-29-AUTO-CONNECT
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Auto connect
aliases:
- class 29
- CL 29
keywords:
- auto connect
- calling window
- destination list
- repetition delay
- remote connection
- class 29
- cl 29
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Auto connect

## Definition

COSEM interface class for controlling automatic outgoing communication attempts.

## Aliases

- class 29
- CL 29

## Domain Tags

- `cosem_class`

## Structured Data

```json metadata
{
  "class_id": 29,
  "version": 2,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "meaning": "OBIS logical name of the auto connect object"
    },
    {
      "attribute_id": 2,
      "name": "mode",
      "type": "enum",
      "mandatory": true,
      "meaning": "Auto-connect operating mode"
    },
    {
      "attribute_id": 3,
      "name": "repetitions",
      "type": "unsigned",
      "mandatory": true,
      "meaning": "Number of repeated outgoing connection attempts"
    },
    {
      "attribute_id": 4,
      "name": "repetition_delay",
      "type": "long-unsigned",
      "mandatory": true,
      "meaning": "Delay between repeated connection attempts"
    },
    {
      "attribute_id": 5,
      "name": "calling_window",
      "type": "array",
      "mandatory": true,
      "meaning": "Time windows during which automatic outgoing calls are permitted"
    },
    {
      "attribute_id": 6,
      "name": "destinations",
      "type": "array",
      "mandatory": true,
      "meaning": "Destination endpoints or identifiers used for outgoing connections"
    }
  ],
  "methods": [],
  "access_semantics": [
    "The auto connect object controls scheduled or triggered outgoing communication attempts.",
    "Calling windows and repetition parameters define retry behavior and should be treated as operational communication policy.",
    "Destination entries may include addresses or endpoint identifiers and should be validated before deployment."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.29 Auto connect (class_id = 29, version = 2)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with outgoing-call mode, retry, calling-window, and destination semantics."
}
```

## Notes

- Use this class when requirements mention scheduled outbound calls, retry delays, calling windows, or remote destination lists.
