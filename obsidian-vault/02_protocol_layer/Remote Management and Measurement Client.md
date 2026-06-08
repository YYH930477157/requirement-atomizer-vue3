---
id: KB-L2-CLIENT-REMOTE-MANAGEMENT
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: client_role
layer: access_model
name: Remote Management and Measurement Client
aliases:
- remote management client
- remote measurement client
- RC
keywords:
- remote management and measurement
- remote clients management and measurement
- remote client
- sap = 0x01
domain_tags:
- client_role
- association
- access_control
- remote_access
relations:
- relation: secured_by
  target: KB-L2-SECURITY-LEVEL-HLS
- relation: associated_with
  target: KB-L2-MANAGEMENT-LOGICAL-DEVICE
- relation: associated_with
  target: KB-L2-METERING-LOGICAL-DEVICE
---

# Remote Management and Measurement Client

## Definition

Client role used by data concentrators, collectors, or central systems for remote point-to-point access to management and measurement functions.

## Aliases

- remote management client
- remote measurement client
- RC

## Domain Tags

- `client_role`
- `association`
- `access_control`
- `remote_access`

## Relations

- `secured_by` -> `KB-L2-SECURITY-LEVEL-HLS`
- `associated_with` -> `KB-L2-MANAGEMENT-LOGICAL-DEVICE`
- `associated_with` -> `KB-L2-METERING-LOGICAL-DEVICE`

## Structured Data

```json metadata
{
  "sap": "0x01",
  "typical_security": "HLS",
  "allowed_service_groups": [
    "GET",
    "SET",
    "ACTION",
    "EventNotification",
    "DataNotification",
    "selective_access"
  ]
}
```

## Notes

