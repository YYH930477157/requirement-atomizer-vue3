---
id: KB-L3-IC-141-HS-PLC-ISO-IEC-12139-1-CPAS-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: HS-PLC ISO/IEC 12139-1 CPAS setup
aliases:
- class 141
- CL 141
keywords:
- hs-plc iso/iec 12139-1 cpas setup
- class 141
- cl 141
- logical_name
- cpas_address
- cpas_ether_type
- master_station_cpas_address
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# HS-PLC ISO/IEC 12139-1 CPAS setup

## Definition

COSEM interface class (class_id = 141, version = 0). Holds the parameters necessary to set up and manage the CPAS layer of the HS-PLC ISO/IEC 12139-1 profile.

## Aliases

- class 141
- CL 141

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the CPAS address of the station, the CPAS sublayer EtherType value, and the master station (typically NNAP) CPAS address.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 141,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "cpas_address", "mode": "static", "type": "long64-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "cpas_ether_type", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "master_station_cpas_address", "mode": "static", "type": "long64-unsigned", "short_name": "x + 0x18" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the CPAS address of the station, the CPAS sublayer EtherType value, and the master station (typically NNAP) CPAS address.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.14.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.14.3.
- 4 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
