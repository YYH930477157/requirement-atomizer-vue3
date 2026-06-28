---
id: KB-L3-IC-80-61334-4-32-LLC-SSCS-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: 61334-4-32 LLC SSCS setup
aliases:
- class 80
- CL 80
keywords:
- 61334-4-32 llc sscs setup
- class 80
- cl 80
- logical_name
- service_node_address
- base_node_address
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# 61334-4-32 LLC SSCS setup

## Definition

COSEM interface class (class_id = 80, version = 0). Holds the addresses provided by the base node during the opening of the convergence layer, allowing the service node to be part of the network managed by the base node.

## Aliases

- class 80
- CL 80

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the service node address assigned during registration and the base node address to which the service node is registered; after deregistration the service node address becomes NEW (0xFFE) and the base node address becomes 0.
- The reset method deallocates the service node address.
- Specific methods: reset (optional).

## Structured Data

```json metadata
{
  "class_id": 80,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "service_node_address", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "base_node_address", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x10" }
  ],
  "methods": [
    { "method_id": 1, "name": "reset", "short_name": "x + 0x20" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the service node address assigned during registration and the base node address to which the service node is registered; after deregistration the service node address becomes NEW (0xFFE) and the base node address becomes 0.",
    "The reset method deallocates the service node address.",
    "Specific methods: reset (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.12.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.12.3.
- 3 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
