---
id: KB-L3-IC-30-COSEM-DATA-PROTECTION
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: COSEM data protection
aliases:
- class 30
- CL 30
- data protection object
- protected cosem data
keywords:
- cosem data protection
- class 30
- cl 30
- protection_buffer
- protection_parameters
- protection status
- protected data
domain_tags:
- cosem_class
- measurement_data
- access_control
- security
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# COSEM data protection

## Definition

COSEM interface class for binding COSEM data to protection metadata, protection parameters, and status used by secure data handling.

## Aliases

- class 30
- CL 30
- data protection object
- protected cosem data

## Domain Tags

- `cosem_class`
- `measurement_data`
- `access_control`
- `security`

## Structured Data

```json metadata
{
  "class_id": 30,
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
      "name": "protection_buffer",
      "type": "octet-string",
      "access": "R",
      "mandatory": true,
      "meaning": "Protected payload or protected representation of the associated COSEM data"
    },
    {
      "attribute_id": 3,
      "name": "protection_parameters",
      "type": "structure",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Parameters controlling how the protected data is generated, verified, or interpreted"
    },
    {
      "attribute_id": 4,
      "name": "protection_status",
      "type": "enum",
      "access": "R",
      "mandatory": true,
      "meaning": "Current status of the protected data object and its protection process"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "protect",
      "mandatory": false,
      "meaning": "Trigger generation or update of protected data when supported by the implementation"
    },
    {
      "method_id": 2,
      "name": "verify",
      "mandatory": false,
      "meaning": "Verify protected data or protection metadata when supported by the implementation"
    }
  ],
  "access_semantics": [
    "protection_buffer is security-sensitive output and should be exposed only according to the configured association and security policy.",
    "protection_parameters control security behavior and should require management-level write privileges.",
    "Protection methods, when available, are active operations and should be treated as high-risk operations in requirements review."
  ],
  "behavior_notes": [
    "Use this class when requirements mention protected COSEM data, data protection status, cryptographic protection parameters, or protected payload verification.",
    "This class belongs with security and access-control requirements, not ordinary measurement display requirements."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.4.3 COSEM data protection (class_id = 30, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with protected payload, protection parameter, status, and high-risk operation semantics."
}
```

## Notes

- Treat writes and active protection operations as security-sensitive.
