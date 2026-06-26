---
id: KB-L3-IC-46-SMTP-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: SMTP setup
aliases:
- class 46
- CL 46
- SMTP configuration
- email setup object
keywords:
- smtp setup
- class 46
- cl 46
- server_port
- user_name
- login_password
- server_address
- sender_address
- smtp server
- email destination
- recipient address
- mail authentication
domain_tags:
- cosem_class
- communication_profile
- smtp
- application_profile
- messaging
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# SMTP setup

## Definition

COSEM interface class (class_id = 46, version = 0) for setting up data exchange using the SMTP protocol. Cardinality 0...n.

## Aliases

- class 46
- CL 46
- SMTP configuration
- email setup object

## Domain Tags

- `cosem_class`
- `communication_profile`
- `smtp`
- `application_profile`
- `messaging`

## Access Semantics

All attributes are **static**, read-write (RW) via the SET service by an authorised management client. logical_name is read-only for all clients. login_password is a sensitive credential; void string means no authentication.

## Behavior Notes

- SMTP setup allows data exchange using the SMTP protocol. Cardinality 0...n.
- **server_port** (attr 2): TCP-UDP port for SMTP. Default 25 (IANA smtp 25/tcp, 25/udp).
- **user_name** (attr 3): user name for SMTP server login.
- **login_password** (attr 4): password for login; void string = no authentication. Sensitive.
- **server_address** (attr 5): server address as octet-string. Can be a DNS-resolvable name or dotted IP (e.g. 163.187.45.87).
- **sender_address** (attr 6): sender address as octet-string (name or dotted IP).
- **No specific methods**: configuration via SET on static attributes.

## Structured Data

```json metadata
{
  "class_id": 46,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "server_port", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "default": 25, "short_name": "0x08"},
    {"attribute_id": 3, "name": "user_name", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "login_password", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x18"},
    {"attribute_id": 5, "name": "server_address", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x20"},
    {"attribute_id": 6, "name": "sender_address", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x28"}
  ],
  "methods": [],
  "access_semantics": [
    "All attributes are static, read-write (RW) via SET by an authorised management client; logical_name read-only for all.",
    "server_port defaults to IANA SMTP port 25.",
    "login_password is sensitive; void string means no authentication.",
    "server_address/sender_address may be DNS names or dotted-IP octet-strings."
  ],
  "behavior_notes": [
    "SMTP setup allows data exchange using the SMTP protocol. Cardinality 0...n.",
    "server_port: default 25 (IANA smtp 25/tcp, 25/udp).",
    "login_password: void string = no authentication; otherwise sensitive.",
    "server_address/sender_address: DNS-resolvable name or dotted IP format."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.9.6 SMTP setup (class_id = 46, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.9.6. Full attributes with access_rights, value defaults, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.9.6 (page 299-300).
- IANA SMTP port: smtp 25/tcp, 25/udp.
- Requirements that change SMTP recipients should be traceable because they affect alarm and report delivery.
