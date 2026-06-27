---
id: KB-L3-IC-151-LTE-MONITORING
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: LTE monitoring
aliases:
- class 151
- CL 151
keywords:
- lte monitoring
- class 151
- cl 151
- logical_name
- LTE_network_parameters
- LTE_quality_of_service
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# LTE monitoring

## Definition

COSEM interface class (class_id = 151, version = 1). Monitors LTE network parameters and quality of service for cellular-connected meters.

## Aliases

- class 151
- CL 151

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Monitors LTE network parameters and quality of service for cellular-connected meters.
- No specific methods defined.

## Structured Data

```json metadata
{
  "class_id": 151,
  "version": 1,
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
      "name": "LTE_network_parameters",
      "mode": "dynamic",
      "type": "LTE_network_parameters_type",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "LTE_quality_of_service",
      "mode": "dynamic",
      "type": "LTE_QoS_type",
      "short_name": "x + 0x10"
    }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Monitors LTE network parameters and quality of service for cellular-connected meters.",
    "No specific methods defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.7.9; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.7.9.
- 3 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
