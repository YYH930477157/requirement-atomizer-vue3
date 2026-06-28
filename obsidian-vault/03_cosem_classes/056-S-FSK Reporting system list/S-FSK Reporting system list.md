---
id: KB-L3-IC-56-S-FSK-REPORTING-SYSTEM-LIST
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: S-FSK Reporting system list
aliases:
- class 56
- CL 56
keywords:
- s-fsk reporting system list
- class 56
- cl 56
- logical_name
- reporting_system_list
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# S-FSK Reporting system list

## Definition

COSEM interface class (class_id = 56, version = 0). Holds the list of reporting systems (server systems that have made a DiscoverReport request and are not yet registered).

## Aliases

- class 56
- CL 56

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the system-titles of server systems that have made a DiscoverReport request and are not yet registered; the list is finite, newest-first, and a system-title appears at most once.
- The list is updated on DiscoverReport (add) and Register (delete) CI_PDU reception.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 56,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "reporting_system_list", "mode": "dynamic", "type": "array", "short_name": "x + 0x08" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the system-titles of server systems that have made a DiscoverReport request and are not yet registered; the list is finite, newest-first, and a system-title appears at most once.",
    "The list is updated on DiscoverReport (add) and Register (delete) CI_PDU reception.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.10.8; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.10.8.
- 2 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
