---
id: KB-OBIS-0-0-43-0-5-255-SECURITY-SETUP-REMOTE-CLIENT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Security Setup - remote client association
aliases:
- Security Setup 0-0:43.0.5.255
- Remote client security setup
keywords:
- 0-0:43.0.5.255
- Security Setup remote client
- remote client security setup
- key management remote association
domain_tags:
- cosem_object
- security_policy
- key_management
- association
relations:
- relation: instance_of
  target: KB-L3-IC-64-SECURITY-SETUP
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Security Setup - remote client association

## Definition

Row-level COSEM object instance for the remote client Security Setup logical name `0-0:43.0.5.255`, used to configure the security policy, security suite, keys, and certificates for remote association contexts.

## Aliases

- Security Setup 0-0:43.0.5.255
- Remote client security setup

## Domain Tags

- `cosem_object`
- `security_policy`
- `key_management`
- `association`

## Relations

- `instance_of` -> `KB-L3-IC-64-SECURITY-SETUP`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:43.0.5.255",
  "likely_interface_class_id": 64,
  "likely_interface_class_name": "Security Setup",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "43 Security Setup",
    "D": "0 security setup instance group",
    "E": "5 remote client association",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    },
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.7 Security setup common instances"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Security Setup object at 0-0:43.0.5.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching remote-client security policy, security suite, key-transfer, and certificate-management requirements.",
    "ABNT Appendix 9 uses this instance in secure communication and security event capture contexts."
  ]
}
```

## Notes

