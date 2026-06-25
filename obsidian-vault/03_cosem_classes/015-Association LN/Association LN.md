---
id: KB-L3-IC-15-ASSOCIATION-LN
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Association LN
aliases:
- Logical Name Association
- class 15
- CL 15
keywords:
- class 15
- cl 15
- association ln
- object_list
- associated_partners_id
- application_context_name
- xdlms_context_info
- authentication_mechanism_name
- secret
- security_setup_reference
- user_list
- access_rights
domain_tags:
- cosem_class
- association
- access_control
---

# Association LN

## Definition

COSEM interface class representing a logical-name association between client and server.

## Aliases

- Logical Name Association
- class 15
- CL 15

## Domain Tags

- `cosem_class`
- `association`
- `access_control`

## Structured Data

```json metadata
{
  "class_id": 15,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "object_list",
      "type": "object_list_type",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "associated_partners_id",
      "type": "associated_partners_type",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "application_context_name",
      "type": "application_context_name",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "xDLMS_context_info",
      "type": "xDLMS_context_type",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "authentication_mechanism_name",
      "type": "mechanism_name",
      "mandatory": true
    },
    {
      "attribute_id": 7,
      "name": "secret",
      "type": "octet-string",
      "mandatory": true
    },
    {
      "attribute_id": 8,
      "name": "association_status",
      "type": "enum",
      "mandatory": true
    },
    {
      "attribute_id": 9,
      "name": "security_setup_reference",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 10,
      "name": "user_list",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 11,
      "name": "current_user",
      "type": "structure",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reply_to_HLS_authentication"
    },
    {
      "method_id": 2,
      "name": "change_HLS_secret"
    },
    {
      "method_id": 3,
      "name": "add_object"
    },
    {
      "method_id": 4,
      "name": "remove_object"
    },
    {
      "method_id": 5,
      "name": "add_user"
    },
    {
      "method_id": 6,
      "name": "remove_user"
    }
  ],
  "common_instances": [
    {
      "name": "Current membership",
      "obis": "0-0:40.0.0.255"
    },
    {
      "name": "Public client association",
      "obis": "0-0:40.0.1.255"
    },
    {
      "name": "Reading client association",
      "obis": "0-0:40.0.2.255"
    },
    {
      "name": "Local client association",
      "obis": "0-0:40.0.3.255"
    },
    {
      "name": "Remote client association",
      "obis": "0-0:40.0.5.255"
    }
  ],
  "access_semantics": [
    "object_list exposes visible COSEM objects together with attribute and method access rights for the association.",
    "security_setup_reference links the association to the Security setup object that manages its security context.",
    "association_status indicates non-associated, association-pending, or associated."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.4 Association LN (class_id = 15, version = 3)"
    }
  ]
}
```

## Notes

