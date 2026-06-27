---
id: KB-L3-IC-47-GSM-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: GSM diagnostic
aliases:
- class 47
- CL 47
keywords:
- gsm diagnostic
- class 47
- cl 47
- logical_name
- operator
- status
- cs_attachment
- ps_status
- cell_info
- adjacent_cells
- capture_time
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# GSM diagnostic

## Definition

COSEM interface class (class_id = 47, version = 2). Stores GSM/GPRS, UMTS, CDMA or LTE cellular network parameters (registration status, signal quality, cell info) for diagnosing communication problems.

## Aliases

- class 47
- CL 47

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Stores GSM/GPRS, UMTS, CDMA or LTE cellular network parameters (registration status, signal quality, cell info) for diagnosing communication problems.
- No specific methods defined.

## Structured Data

```json metadata
{
  "class_id": 47,
  "version": 2,
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
      "name": "operator",
      "mode": "dynamic",
      "type": "visible-string",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "status",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "cs_attachment",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "ps_status",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "cell_info",
      "mode": "dynamic",
      "type": "cell_info_type",
      "short_name": "x + 0x30"
    },
    {
      "attribute_id": 7,
      "name": "adjacent_cells",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 8,
      "name": "capture_time",
      "mode": "dynamic",
      "type": "date-time",
      "short_name": "x + 0x40"
    }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Stores GSM/GPRS, UMTS, CDMA or LTE cellular network parameters (registration status, signal quality, cell info) for diagnosing communication problems.",
    "No specific methods defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.7.8; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.7.8.
- 8 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
