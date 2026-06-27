---
id: KB-L3-IC-98-MPL-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: MPL diagnostic
aliases:
- class 98
- CL 98
keywords:
- mpl diagnostic
- class 98
- cl 98
- logical_name
- proactive_forwarding
- z
- tunit
- se_lifetime
- dm_k
- dm_imin
- dm_imax
- dm_t_exp
- c_k
- c_imin
- c_imax
- c_t_exp
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# MPL diagnostic

## Definition

COSEM interface class (class_id = 98, version = 0). Provides MPL (RFC 7731) multicast forwarding diagnostic parameters for the Wi-SUN network.

## Aliases

- class 98
- CL 98

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Provides MPL (RFC 7731) multicast forwarding diagnostic parameters for the Wi-SUN network.
- Specific methods: reset.

## Structured Data

```json metadata
{
  "class_id": 98,
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
      "name": "proactive_forwarding",
      "mode": "dynamic",
      "type": "boolean",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "z",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 4,
      "name": "tunit",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 5,
      "name": "se_lifetime",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 6,
      "name": "dm_k",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x30"
    },
    {
      "attribute_id": 7,
      "name": "dm_imin",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 8,
      "name": "dm_imax",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x40"
    },
    {
      "attribute_id": 9,
      "name": "dm_t_exp",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x48"
    },
    {
      "attribute_id": 10,
      "name": "c_k",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x50"
    },
    {
      "attribute_id": 11,
      "name": "c_imin",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x58"
    },
    {
      "attribute_id": 12,
      "name": "c_imax",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x60"
    },
    {
      "attribute_id": 13,
      "name": "c_t_exp",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x68"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "short_name": "x + 0x70"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Provides MPL (RFC 7731) multicast forwarding diagnostic parameters for the Wi-SUN network.",
    "Specific methods: reset."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.18.4; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.18.4.
- 13 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
