---
id: KB-L3-IC-12-ASSOCIATION-SN
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Association SN
aliases:
- class 12
- CL 12
keywords:
- association sn
- short name association
- object list
- access rights list
- security setup reference
- class 12
- cl 12
domain_tags:
- cosem_class
- access_control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Association SN

## Definition

COSEM interface class for short-name association objects, access rights, and xDLMS context negotiation.

## Aliases

- class 12
- CL 12

## Domain Tags

- `cosem_class`
- `access_control`

## Structured Data

```json metadata
{
  "class_id": 12,
  "version": 4,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "meaning": "OBIS logical name of the Association SN object"
    },
    {
      "attribute_id": 2,
      "name": "object_list",
      "type": "array",
      "mandatory": true,
      "meaning": "List of objects visible in the short-name association, including class, version, logical name, and short-name base"
    },
    {
      "attribute_id": 3,
      "name": "associated_partners_id",
      "type": "structure",
      "mandatory": true,
      "meaning": "Client and server SAP identifiers participating in the association"
    },
    {
      "attribute_id": 4,
      "name": "application_context_name",
      "type": "octet-string",
      "mandatory": true,
      "meaning": "xDLMS application context negotiated for the association"
    },
    {
      "attribute_id": 5,
      "name": "xDLMS_context_info",
      "type": "structure",
      "mandatory": true,
      "meaning": "Negotiated conformance, PDU size, and context parameters"
    },
    {
      "attribute_id": 6,
      "name": "authentication_mechanism_name",
      "type": "octet-string",
      "mandatory": true,
      "meaning": "Authentication mechanism used by the association"
    },
    {
      "attribute_id": 7,
      "name": "secret",
      "type": "octet-string",
      "mandatory": false,
      "meaning": "Association secret used by authentication mechanisms"
    },
    {
      "attribute_id": 8,
      "name": "association_status",
      "type": "enum",
      "mandatory": true,
      "meaning": "Current association state"
    },
    {
      "attribute_id": 9,
      "name": "security_setup_reference",
      "type": "octet-string[6]",
      "mandatory": false,
      "meaning": "Logical name of the related Security setup object"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reply_to_HLS_authentication",
      "meaning": "Completes high-level security authentication where applicable"
    },
    {
      "method_id": 2,
      "name": "change_HLS_secret",
      "meaning": "Changes the association secret used by HLS mechanisms"
    }
  ],
  "access_semantics": [
    "Association SN controls which short-name objects and access rights are visible to a client.",
    "The object list and access rights define the implementable data model for this client association.",
    "Secret and authentication fields are security-sensitive and should be handled as credentials.",
    "Security setup reference links the association to security policy, suite, and key-management configuration."
  ],
  "common_instances": [
    {
      "name": "Association SN",
      "obis_pattern": "0-0:40.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.12 Association SN (class_id = 12, version = 4)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with object list, association partners, xDLMS context, authentication, HLS methods, and security setup semantics."
}
```

## Notes

- Use this class when a requirement mentions short-name association, object list visibility, access rights, HLS authentication, or association secrets.
