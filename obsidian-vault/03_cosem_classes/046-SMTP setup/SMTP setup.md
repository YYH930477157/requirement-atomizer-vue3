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
- smtp server
- email destination
- sender address
- recipient address
- mail authentication
domain_tags:
- cosem_class
- communication_profile
- application_profile
- messaging
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# SMTP setup

## Definition

COSEM interface class for configuring SMTP setup parameters in DLMS/COSEM devices.

## Aliases

- class 46
- CL 46
- SMTP configuration
- email setup object

## Domain Tags

- `cosem_class`
- `communication_profile`
- `application_profile`
- `messaging`

## Structured Data

```json metadata
{
  "class_id": 46,
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
      "name": "SMTP_server",
      "type": "visible-string",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Server address or host name used for outgoing SMTP messages"
    },
    {
      "attribute_id": 3,
      "name": "sender_address",
      "type": "visible-string",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Sender address used by the device for SMTP notifications"
    },
    {
      "attribute_id": 4,
      "name": "recipient_addresses",
      "type": "array",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Configured e-mail recipients for SMTP based notifications or reports"
    },
    {
      "attribute_id": 5,
      "name": "authentication",
      "type": "structure",
      "access": "R/W",
      "mandatory": false,
      "meaning": "SMTP authentication data when required by the mail server"
    }
  ],
  "methods": [],
  "access_semantics": [
    "SMTP_server, sender_address, and recipient_addresses define where device-generated notifications are sent and should be managed as communication configuration.",
    "Authentication values are security-sensitive and must not be exposed to low-privilege clients.",
    "Recipient configuration changes can redirect alarms or reports and should be audited."
  ],
  "behavior_notes": [
    "Use this class when requirements mention SMTP, e-mail alarm delivery, sender address, recipient list, or mail server configuration.",
    "SMTP setup belongs to application-level communication requirements and often depends on TCP-UDP/IP network setup."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.24 SMTP setup (class_id = 46, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with server, sender, recipient, authentication, and notification redirection semantics."
}
```

## Notes

- Requirements that change SMTP recipients should be traceable because they affect alarm and report delivery.
