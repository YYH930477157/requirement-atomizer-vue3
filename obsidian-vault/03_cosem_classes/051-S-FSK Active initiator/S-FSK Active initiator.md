---
id: KB-L3-IC-51-S-FSK-ACTIVE-INITIATOR
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: S-FSK Active initiator
aliases:
- class 51
- CL 51
keywords:
- s-fsk active initiator
- class 51
- cl 51
- logical_name
- active_initiator
- reset_new_not_synchronized
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# S-FSK Active initiator

## Definition

COSEM interface class (class_id = 51, version = 0). Stores the data of the active initiator, i.e. the client system which has last registered the server system with a CIASE Register request.

## Aliases

- class 51
- CL 51

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Stores the identifiers of the active initiator (system title, MAC address and L-SAP selector), i.e. the client system that has last registered the server.
- The value of active_initiator can be updated by the reset_NEW_not_synchronized method or by the CIASE Register service.
- Specific methods: reset_NEW_not_synchronized.

## Structured Data

```json metadata
{
  "class_id": 51,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "active_initiator", "mode": "dynamic", "type": "initiator_descriptor", "short_name": "x + 0x08" }
  ],
  "methods": [
    { "method_id": 1, "name": "reset_NEW_not_synchronized", "short_name": "x + 0x10" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Stores the identifiers of the active initiator (system title, MAC address and L-SAP selector), i.e. the client system that has last registered the server.",
    "The value of active_initiator can be updated by the reset_NEW_not_synchronized method or by the CIASE Register service.",
    "Specific methods: reset_NEW_not_synchronized."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.10.4; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.10.4.
- 2 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
