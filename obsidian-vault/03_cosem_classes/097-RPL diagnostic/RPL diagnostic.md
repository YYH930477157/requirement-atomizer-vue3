---
id: KB-L3-IC-97-RPL-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: RPL diagnostic
aliases:
- class 97
- CL 97
keywords:
- rpl diagnostic
- class 97
- cl 97
- logical_name
- rpl_instance_id
- dodag_version_number
- dodag_rank
- grounded
- mode_of_operation
- dodag_prf
- dodag_dtsn
- dodag_id
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# RPL diagnostic

## Definition

COSEM interface class (class_id = 97, version = 0). Provides RPL (RFC 6550) routing diagnostic information about the device's DODAG (rank, version, mode of operation).

## Aliases

- class 97
- CL 97

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Provides RPL (RFC 6550) routing diagnostic information about the device's DODAG (rank, version, mode of operation).
- Specific methods: reset.

## Structured Data

```json metadata
{
  "class_id": 97,
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
      "name": "rpl_instance_id",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "dodag_version_number",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "dodag_rank",
      "mode": "dynamic",
      "type": "long",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "grounded",
      "mode": "dynamic",
      "type": "boolean",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "mode_of_operation",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 7,
      "name": "dodag_prf",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x30"
    },
    {
      "attribute_id": 8,
      "name": "dodag_dtsn",
      "mode": "dynamic",
      "type": "unsigned",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 9,
      "name": "dodag_id",
      "mode": "dynamic",
      "type": "octet-string",
      "short_name": "x + 0x40"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "short_name": "x + 0x48"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Provides RPL (RFC 6550) routing diagnostic information about the device's DODAG (rank, version, mode of operation).",
    "Specific methods: reset."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.18.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.18.3.
- 9 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
