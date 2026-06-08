---
id: KB-L2-SECURITY-POLICY-BITS
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: security_policy_map
layer: security_model
name: Security Policy Bit Map
aliases:
- security states
- security policy states
keywords:
- security policy
- security states
- request authenticated
- encrypted request
- digitally signed request
- response authenticated
- encrypted response
- digitally signed response
domain_tags:
- security_policy
- configuration_check
---

# Security Policy Bit Map

## Definition

Bit-level meaning of DLMS/COSEM security policy states.

## Aliases

- security states
- security policy states

## Domain Tags

- `security_policy`
- `configuration_check`

## Structured Data

```json metadata
{
  "bits": [
    {
      "bit": 0,
      "meaning": "not used, must be set to 0"
    },
    {
      "bit": 1,
      "meaning": "not used, must be set to 0"
    },
    {
      "bit": 2,
      "meaning": "request authenticated"
    },
    {
      "bit": 3,
      "meaning": "encrypted request"
    },
    {
      "bit": 4,
      "meaning": "digitally signed request"
    },
    {
      "bit": 5,
      "meaning": "response authenticated"
    },
    {
      "bit": 6,
      "meaning": "encrypted response"
    },
    {
      "bit": 7,
      "meaning": "digitally signed response"
    }
  ]
}
```

## Notes

