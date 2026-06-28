---
id: KB-L3-IC-105-ZIGBEE-TUNNEL-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ZigBee tunnel setup
aliases:
- class 105
- CL 105
keywords:
- zigbee tunnel setup
- class 105
- cl 105
- logical_name
- maximum_incoming_transfer_size
- maximum_outgoing_transfer_size
- protocol_address
- close_tunnel_timeout
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ZigBee tunnel setup

## Definition

COSEM interface class (class_id = 105, version = 0). Configures a ZigBee® tunnel established between two ZigBee® PRO devices to allow DLMS APDUs to be transferred, extending WAN connectivity to ZigBee® devices not connected to the WAN.

## Aliases

- class 105
- CL 105

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the tunnel transfer-size limits (incoming/outgoing), the protocol address and the close-tunnel timeout (seconds, restarted on each received command).
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 105,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "maximum_incoming_transfer_size", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "maximum_outgoing_transfer_size", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "protocol_address", "mode": "static", "type": "octet-string", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "close_tunnel_timeout", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x20" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the tunnel transfer-size limits (incoming/outgoing), the protocol address and the close-tunnel timeout (seconds, restarted on each received command).",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.15.6; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.15.6.
- 5 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
