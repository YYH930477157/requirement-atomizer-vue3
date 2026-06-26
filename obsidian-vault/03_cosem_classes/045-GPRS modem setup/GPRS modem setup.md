---
id: KB-L3-IC-45-GPRS-MODEM-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: GPRS modem setup
aliases:
- class 45
- CL 45
- GPRS modem configuration
- cellular modem setup
keywords:
- gprs modem setup
- class 45
- cl 45
- apn
- pin_code
- pin code
- quality_of_service
- cellular modem
- gprs qos
domain_tags:
- cosem_class
- communication_profile
- gprs
- cellular
- network_setup
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# GPRS modem setup

## Definition

COSEM interface class (class_id = 45, version = 0) for setting up GPRS modems, handling all data necessary for modem management. Cardinality 0...n.

## Aliases

- class 45
- CL 45
- GPRS modem configuration
- cellular modem setup

## Domain Tags

- `cosem_class`
- `communication_profile`
- `gprs`
- `cellular`
- `network_setup`

## Access Semantics

All attributes are **static**, read-write (RW) via the SET service by an authorised management client. logical_name is read-only for all clients. PIN_code is a sensitive SIM authentication credential that must be protected.

## Behavior Notes

- GPRS modem setup handles all data necessary for GPRS modem management. Cardinality 0...n.
- **APN** (attr 2): Access Point Name, the GPRS network access point identifier.
- **PIN_code** (attr 3): SIM card PIN code as long-unsigned. Sensitive; required for SIM authentication.
- **quality_of_service** (attr 4): structure carrying GPRS QoS parameters (e.g. peak/mean throughput, reliability class).
- **No specific methods**: configuration is done entirely via SET on static attributes.

## Structured Data

```json metadata
{
  "class_id": 45,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "APN", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x08"},
    {"attribute_id": 3, "name": "PIN_code", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "quality_of_service", "type": "structure", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x18"}
  ],
  "methods": [],
  "access_semantics": [
    "All attributes are static, read-write (RW) via SET by an authorised management client; logical_name read-only for all.",
    "APN identifies the GPRS network access point.",
    "PIN_code is the SIM PIN (sensitive, required for SIM authentication).",
    "quality_of_service carries GPRS QoS parameters affecting modem connectivity."
  ],
  "behavior_notes": [
    "GPRS modem setup handles all data necessary for GPRS modem management. Cardinality 0...n.",
    "APN: Access Point Name for the GPRS network.",
    "PIN_code: SIM card PIN (long-unsigned); sensitive.",
    "quality_of_service: structure of GPRS QoS parameters (peak/mean throughput, reliability class)."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.7.7 GPRS modem setup (class_id = 45, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.7.7. Full attributes with access_rights, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.7.7 (page 261).
- Treat APN and PIN handling as configuration requirements, not as measurement data.
