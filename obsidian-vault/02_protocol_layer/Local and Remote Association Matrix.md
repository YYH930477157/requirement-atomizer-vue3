---
id: KB-L2-ASSOCIATION-MATRIX
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: association_rule
layer: access_model
name: Local and Remote Association Matrix
aliases:
- Table 2 association matrix
- local and remote associations
keywords:
- local associations and remote
- local and remote associations
- association matrix
- without security
- high level of security
- low level security
domain_tags:
- association
- security_policy
- access_control
relations:
- relation: uses
  target: KB-L2-SECURITY-LEVEL-HLS
- relation: uses
  target: KB-L2-SECURITY-LEVEL-LLS
---

# Local and Remote Association Matrix

## Definition

Association matrix that maps client roles to management and metering logical devices and their required security level.

## Aliases

- Table 2 association matrix
- local and remote associations

## Domain Tags

- `association`
- `security_policy`
- `access_control`

## Relations

- `uses` -> `KB-L2-SECURITY-LEVEL-HLS`
- `uses` -> `KB-L2-SECURITY-LEVEL-LLS`

## Structured Data

```json metadata
{
  "rules": [
    {
      "client": "Public Client",
      "management_logical_device": "without_security",
      "metering_logical_device": "not_applicable"
    },
    {
      "client": "Remote Management and Measurement Client",
      "management_logical_device": "HLS",
      "metering_logical_device": "HLS"
    },
    {
      "client": "Local Management and Measurement Client",
      "management_logical_device": "HLS",
      "metering_logical_device": "HLS"
    },
    {
      "client": "Read Client",
      "management_logical_device": "LLS",
      "metering_logical_device": "LLS"
    }
  ]
}
```

## Notes

