---
id: KB-L2-CLIENT-PUBLIC
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: client_role
layer: access_model
name: Public Client
aliases:
- client public
- public customer
keywords:
- public client
- client public
- public customer
- sap = 0x10
domain_tags:
- client_role
- association
- access_control
relations:
- relation: associated_with
  target: KB-L2-MANAGEMENT-LOGICAL-DEVICE
- relation: uses
  target: KB-L2-XDLMS-SERVICES
---

# Public Client

## Definition

Client role used to reveal the structure of an unknown metering device, typically through the management logical device without security.

## Aliases

- client public
- public customer

## Domain Tags

- `client_role`
- `association`
- `access_control`

## Relations

- `associated_with` -> `KB-L2-MANAGEMENT-LOGICAL-DEVICE`
- `uses` -> `KB-L2-XDLMS-SERVICES`

## Structured Data

```json metadata
{
  "sap": "0x10",
  "typical_security": "without_security",
  "allowed_service_groups": [
    "GET",
    "selective_access"
  ],
  "limitations": [
    "No access to measurement data requiring authentication",
    "No read or write access to password values"
  ]
}
```

## Notes

