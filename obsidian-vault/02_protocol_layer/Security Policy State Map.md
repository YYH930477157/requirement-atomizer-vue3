---
id: KB-L2-SECURITY-POLICY-STATES
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: security_policy_map
layer: security_model
name: Security Policy State Map
aliases:
- policy security
- security policy states
keywords:
- policy security
- all messages are authenticated
- all messages are encrypted
- all messages are authenticated and encrypted
domain_tags:
- security_policy
- configuration_check
---

# Security Policy State Map

## Definition

State-level map for DLMS/COSEM message authentication and encryption policy.

## Aliases

- policy security
- security policy states

## Domain Tags

- `security_policy`
- `configuration_check`

## Structured Data

```json metadata
{
  "states": [
    {
      "state": "0",
      "meaning": "anything"
    },
    {
      "state": "1",
      "meaning": "all messages are authenticated"
    },
    {
      "state": "2",
      "meaning": "all messages are encrypted"
    },
    {
      "state": "3",
      "meaning": "all messages are authenticated and encrypted"
    },
    {
      "state": "other",
      "meaning": "reserved"
    }
  ]
}
```

## Notes

