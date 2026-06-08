---
id: KB-L2-CLIENT-READ
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: client_role
layer: access_model
name: Read Client
aliases:
- Reading Client
- PC
keywords:
- read client
- reading client
- sap = 0x03
domain_tags:
- client_role
- association
- access_control
- read_access
relations:
- relation: secured_by
  target: KB-L2-SECURITY-LEVEL-LLS
- relation: associated_with
  target: KB-L2-MANAGEMENT-LOGICAL-DEVICE
- relation: associated_with
  target: KB-L2-METERING-LOGICAL-DEVICE
---

# Read Client

## Definition

Client role used for reading parameters and energy data. Password access through LLS is typically required.

## Aliases

- Reading Client
- PC

## Domain Tags

- `client_role`
- `association`
- `access_control`
- `read_access`

## Relations

- `secured_by` -> `KB-L2-SECURITY-LEVEL-LLS`
- `associated_with` -> `KB-L2-MANAGEMENT-LOGICAL-DEVICE`
- `associated_with` -> `KB-L2-METERING-LOGICAL-DEVICE`

## Structured Data

```json metadata
{
  "sap": "0x03",
  "typical_security": "LLS",
  "allowed_service_groups": [
    "GET",
    "selective_access"
  ],
  "limitations": [
    "No read or write access to password values"
  ]
}
```

## Notes

