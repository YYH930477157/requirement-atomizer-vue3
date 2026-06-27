---
id: KB-L3-IC-143-HS-PLC-ISO-IEC-12139-1-HDLC-SSAS-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: HS-PLC ISO/IEC 12139-1 HDLC SSAS setup
aliases:
- class 143
- CL 143
keywords:
- hs-plc iso/iec 12139-1 hdlc ssas setup
- class 143
- cl 143
- logical_name
- master_station_id
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# HS-PLC ISO/IEC 12139-1 HDLC SSAS setup

## Definition

COSEM interface class (class_id = 143, version = 0). Holds parameters to set up the HDLC SSAS of the HS-PLC ISO/IEC 12139-1 profile (master station identifier).

## Aliases

- class 143
- CL 143

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds parameters to set up the HDLC SSAS of the HS-PLC ISO/IEC 12139-1 profile (master station identifier).
- No specific methods defined.

## Structured Data

```json metadata
{
  "class_id": 143,
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
      "name": "master_station_id",
      "mode": "static",
      "type": "long64-unsigned",
      "short_name": "x + 0x08"
    }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds parameters to set up the HDLC SSAS of the HS-PLC ISO/IEC 12139-1 profile (master station identifier).",
    "No specific methods defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.14.5; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.14.5.
- 2 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
