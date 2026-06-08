---
id: KB-L2-SECURITY-SUITES
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: security_suite_set
layer: security_model
name: DLMS/COSEM Security Suites
aliases:
- security suite
- set of security
keywords:
- set of security
- security suite
- aes-gcm-128
- aes-gcm-256
- ecdh-ecdsa
- sha-256
- sha-384
domain_tags:
- security_policy
- encryption
- digital_signature
- key_management
---

# DLMS/COSEM Security Suites

## Definition

Available DLMS/COSEM cryptographic suites and related algorithms.

## Aliases

- security suite
- set of security

## Domain Tags

- `security_policy`
- `encryption`
- `digital_signature`
- `key_management`

## Structured Data

```json metadata
{
  "suites": [
    {
      "id": "0",
      "name": "AES-GCM-128",
      "authenticated_encryption": "AES-GCM-128",
      "digital_signature": null,
      "key_agreement": null,
      "hash": null,
      "transport_key": "AES-128 key wrap",
      "compression": null
    },
    {
      "id": "1",
      "name": "ECDH-ECDSA-AES-GCM-128-SHA-256",
      "authenticated_encryption": "AES-GCM-128",
      "digital_signature": "ECDSA with P-256",
      "key_agreement": "ECDH with P-256",
      "hash": "SHA-256",
      "transport_key": "AES-128 key wrap",
      "compression": "V.44"
    },
    {
      "id": "2",
      "name": "ECDH-ECDSA-AES-GCM-256-SHA-384",
      "authenticated_encryption": "AES-GCM-256",
      "digital_signature": "ECDSA with P-384",
      "key_agreement": "ECDH with P-384",
      "hash": "SHA-384",
      "transport_key": "AES-256 key wrap",
      "compression": "V.44"
    }
  ]
}
```

## Notes

