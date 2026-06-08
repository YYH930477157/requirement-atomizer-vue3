---
id: KB-L2-CLIENT-LOCAL-MANAGEMENT
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: client_role
layer: access_model
name: Local Management and Measurement Client
aliases:
- local management client
- local measurement client
- LC
keywords:
- local management and measurement
- local client
- sap = 0x02
domain_tags:
- client_role
- association
- access_control
- local_access
relations:
- relation: secured_by
  target: KB-L2-SECURITY-LEVEL-HLS
- relation: associated_with
  target: KB-L2-MANAGEMENT-LOGICAL-DEVICE
- relation: associated_with
  target: KB-L2-METERING-LOGICAL-DEVICE
---

# Local Management and Measurement Client

## Definition

Client role used for local access by a concentrator, collector, or central system. It generally has similar rights to the remote management client, with restrictions on remote association attributes.

## Aliases

- local management client
- local measurement client
- LC

## Domain Tags

- `client_role`
- `association`
- `access_control`
- `local_access`

## Relations

- `secured_by` -> `KB-L2-SECURITY-LEVEL-HLS`
- `associated_with` -> `KB-L2-MANAGEMENT-LOGICAL-DEVICE`
- `associated_with` -> `KB-L2-METERING-LOGICAL-DEVICE`

## Structured Data

```json metadata
{
  "sap": "0x02",
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

