---
id: KB-L3-IC-68-ARBITRATOR
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Arbitrator
aliases:
- class 68
- CL 68
keywords:
- arbitrator
- class 68
- cl 68
- logical_name
- actions
- permissions_table
- weightings_table
- most_recent_requests_table
- last_outcome
- request_action
- reset
domain_tags:
- cosem_class
- access_control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Arbitrator

## Definition

COSEM interface class (class_id = 68, version = 0). Determines, from pre-configured permissions and weightings, which action is carried out when multiple actors may request potentially conflicting actions to control the same resource.

## Aliases

- class 68
- CL 68

## Domain Tags

- `cosem_class`
- `access_control`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Determines, from pre-configured permissions_table and weightings_table, which action wins when multiple actors request conflicting actions on a single resource (one Arbitrator per controlled resource).
- Actions are requested via request_action; the AP checks the actor's permissions, updates most_recent_requests_table, sums the weightings, and on a unique highest total weight writes last_outcome and executes the corresponding Script table script.
- Specific methods: request_action (mandatory), reset (optional).

## Structured Data

```json metadata
{
  "class_id": 68,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "actions", "mode": "static", "type": "array", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "permissions_table", "mode": "static", "type": "array", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "weightings_table", "mode": "static", "type": "array", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "most_recent_requests_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "last_outcome", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x28" }
  ],
  "methods": [
    { "method_id": 1, "name": "request_action", "short_name": "x + 0x30" },
    { "method_id": 2, "name": "reset", "short_name": "x + 0x38" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Determines, from pre-configured permissions_table and weightings_table, which action wins when multiple actors request conflicting actions on a single resource (one Arbitrator per controlled resource).",
    "Actions are requested via request_action; the AP checks the actor's permissions, updates most_recent_requests_table, sums the weightings, and on a unique highest total weight writes last_outcome and executes the corresponding Script table script.",
    "Specific methods: request_action (mandatory), reset (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.5.12; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.5.12.
- 6 attributes, 2 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
