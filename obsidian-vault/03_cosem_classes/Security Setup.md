---
id: KB-L3-IC-64-SECURITY-SETUP
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Security Setup
aliases:
- class 64
- CL 64
keywords:
- class 64
- cl 64
- security setup
- security_policy
- security_suite
- client_system_title
- server_system_title
- certificate
domain_tags:
- cosem_class
- security_policy
- key_management
---

# Security Setup

## Definition

COSEM interface class for security policy, security suite, system titles, certificates, and key management methods.

## Aliases

- class 64
- CL 64

## Domain Tags

- `cosem_class`
- `security_policy`
- `key_management`

## Structured Data

```json metadata
{
  "class_id": 64,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "security_policy",
      "type": "security_policy_type",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "security_suite",
      "type": "enum",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "client_system_title",
      "type": "octet-string",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "server_system_title",
      "type": "octet-string",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "certificates",
      "type": "array",
      "mandatory": false
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "security_activate"
    },
    {
      "method_id": 2,
      "name": "key_transfer"
    },
    {
      "method_id": 3,
      "name": "key_agreement"
    },
    {
      "method_id": 4,
      "name": "generate_key_pair"
    },
    {
      "method_id": 5,
      "name": "generate_certificate_request"
    },
    {
      "method_id": 6,
      "name": "import_certificate"
    },
    {
      "method_id": 7,
      "name": "export_certificate"
    },
    {
      "method_id": 8,
      "name": "remove_certificate"
    }
  ],
  "common_instances": [
    {
      "name": "Security Setup for remote client association",
      "obis": "0-0:43.0.5.255"
    },
    {
      "name": "Security Setup for local client association",
      "obis": "0-0:43.0.3.255"
    }
  ],
  "access_semantics": [
    "Instances contain the security suite and policy applicable between a client and server identified by their system titles.",
    "The class provides methods to increase security level and manage symmetric keys, asymmetric key pairs, and certificates."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.7 Security setup (class_id = 64, version = 1)"
    }
  ]
}
```

## Notes

