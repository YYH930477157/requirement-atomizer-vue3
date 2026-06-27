---
id: KB-L3-IC-152-COAP-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: CoAP setup
aliases:
- class 152
- CL 152
keywords:
- coap setup
- class 152
- cl 152
- logical_name
- UDP_reference
- ack_timeout
- ack_random_factor
- max_retransmit
- nstart
- delay_ack_timeout
- exponential_back_off
- probing_rate
- CoAP_uri_path
- transport_mode
- version
- token_length
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# CoAP setup

## Definition

COSEM interface class (class_id = 152, version = 0). Sets up CoAP transport parameters (UDP reference, ACK/retransmit timers, uri-path, transport mode, token length).

## Aliases

- class 152
- CL 152

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Sets up CoAP transport parameters (UDP reference, ACK/retransmit timers, uri-path, transport mode, token length).
- No specific methods defined.

## Structured Data

```json metadata
{
  "class_id": 152,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "mode": "static",
      "type": "octet-string"
    },
    {
      "attribute_id": 2,
      "name": "UDP_reference",
      "mode": "static",
      "type": "octet-string",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "ack_timeout",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "ack_random_factor",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "max_retransmit",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "nstart",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 7,
      "name": "delay_ack_timeout",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x30"
    },
    {
      "attribute_id": 8,
      "name": "exponential_back_off",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 9,
      "name": "probing_rate",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x40"
    },
    {
      "attribute_id": 10,
      "name": "CoAP_uri_path",
      "mode": "static",
      "type": "octet-string",
      "short_name": "x + 0x48"
    },
    {
      "attribute_id": 11,
      "name": "transport_mode",
      "mode": "static",
      "type": "enum",
      "short_name": "x + 0x50"
    },
    {
      "attribute_id": 12,
      "name": "version",
      "mode": "dynamic",
      "type": "CHOICE",
      "short_name": "x + 0x58"
    },
    {
      "attribute_id": 13,
      "name": "token_length",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x60"
    }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Sets up CoAP transport parameters (UDP reference, ACK/retransmit timers, uri-path, transport mode, token length).",
    "No specific methods defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.9.8; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.9.8.
- 13 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
