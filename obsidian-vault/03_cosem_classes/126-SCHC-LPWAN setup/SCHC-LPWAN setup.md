---
id: KB-L3-IC-126-SCHC-LPWAN-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: SCHC-LPWAN setup
aliases:
- class 126
- CL 126
keywords:
- schc-lpwan setup
- class 126
- cl 126
- logical_name
- lpwan_reference
- schc_cd_rules
- schc_fr_param
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# SCHC-LPWAN setup

## Definition

COSEM interface class (class_id = 126, version = 0). Sets up SCHC (RFC 8724) compression/decompression and fragmentation/reassembly rules for DLMS over LPWAN.

## Aliases

- class 126
- CL 126

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Sets up SCHC (RFC 8724) compression/decompression and fragmentation/reassembly rules for DLMS over LPWAN.
- No specific methods defined.

## Structured Data

```json metadata
{
  "class_id": 126,
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
      "name": "lpwan_reference",
      "mode": "static",
      "type": "octet-string",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "schc_cd_rules",
      "mode": "static",
      "type": "array",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "schc_fr_param",
      "mode": "static",
      "type": "structure",
      "short_name": "x + 0x18"
    }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Sets up SCHC (RFC 8724) compression/decompression and fragmentation/reassembly rules for DLMS over LPWAN.",
    "No specific methods defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.16.2.1; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.16.2.1.
- 4 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
