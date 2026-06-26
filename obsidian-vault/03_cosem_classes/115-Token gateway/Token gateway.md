---
id: KB-L3-IC-115-TOKEN-GATEWAY
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Token gateway
aliases:
- class 115
- CL 115
keywords:
- token gateway
- class 115
- cl 115
- token
- token_time
- token_description
- token_delivery_method
- token_status
- enter
domain_tags:
- cosem_class
- payment_metering
- token
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Token gateway

## Definition

COSEM interface class (class_id = 115, version = 0) implementing the Token Carrier Interface. A single Token gateway instance is instantiated for each Account object (and hence each supply contract). Cardinality 0...n.

## Aliases

- class 115
- CL 115

## Domain Tags

- `cosem_class`
- `payment_metering`
- `token`

## Access Semantics

logical_name is read-only for all clients. All other attributes are **dynamic** (dyn.) — they reflect token-entry runtime state and are read-only (R) for operational clients. Tokens are entered via the mandatory `enter` method, which populates the dynamic attributes. One Token gateway instance per Account/supply contract.

## Behavior Notes

- Token gateway implements the Token Carrier Interface; one instance per Account/supply contract. Cardinality 0...n.
- **token** (attr 2): dynamic octet-string, the entered token value.
- **token_time** (attr 3): dynamic octet-string, time the token was entered.
- **token_description** (attr 4): dynamic array, descriptive metadata of the token.
- **token_delivery_method** (attr 5): dynamic enum, how the token was delivered (e.g. keypad, optical, remote).
- **token_status** (attr 6): dynamic structure, processing status/result of the token (accepted/rejected/invalid etc.).

## Methods

- **enter** (method 1): enter a token into the gateway (param: data). **Mandatory** — the primary token-entry action that populates the dynamic attributes.

## Structured Data

```json metadata
{
  "class_id": 115,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "token", "type": "octet-string", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x08"},
    {"attribute_id": 3, "name": "token_time", "type": "octet-string", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x10"},
    {"attribute_id": 4, "name": "token_description", "type": "array", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x18"},
    {"attribute_id": 5, "name": "token_delivery_method", "type": "enum", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x20"},
    {"attribute_id": 6, "name": "token_status", "type": "structure", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x28"}
  ],
  "methods": [
    {"method_id": 1, "name": "enter", "parameter_type": "data", "mandatory": true, "short_name": "0x30", "meaning": "Enter a token into the gateway (primary token-entry action)."}
  ],
  "access_semantics": [
    "logical_name read-only for all; all other attributes are dynamic read-only (R).",
    "Tokens are entered via the mandatory enter method, which populates the dynamic token/token_time/description/delivery_method/status attributes.",
    "One Token gateway instance per Account/supply contract."
  ],
  "behavior_notes": [
    "Token gateway implements the Token Carrier Interface; one instance per Account/supply contract. Cardinality 0...n.",
    "token/token_time/token_description: dynamic, reflect the most recently entered token.",
    "token_delivery_method: enum (keypad/optical/remote etc.).",
    "token_status: structure with processing result (accepted/rejected/invalid).",
    "enter method is mandatory — the sole token-entry action."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.6.5 Token gateway (class_id = 115, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.6.5. Full 6 attributes with access_rights (all dynamic R except logical_name), mandatory enter method, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.6.5 (page 242).
- One instance per Account object / supply contract.
