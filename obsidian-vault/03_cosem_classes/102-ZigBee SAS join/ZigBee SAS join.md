---
id: KB-L3-IC-102-ZIGBEE-SAS-JOIN
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ZigBee SAS join
aliases:
- class 102
- CL 102
keywords:
- zigbee sas join
- class 102
- cl 102
- logical_name
- scan_attempts
- time_between_scans
- rejoin_interval
- rejoin_retry_interval
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ZigBee SAS join

## Definition

COSEM interface class (class_id = 102, version = 0). Configures the behaviour of a ZigBee® PRO device on joining or loss of connection to the network. Present in all devices where a DLMS server controls the ZigBee® radio, but not used by a coordinator.

## Aliases

- class 102
- CL 102

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the rejoin/scan tuning parameters (scan attempts, time between scans, rejoin interval and rejoin retry interval, in seconds).
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 102,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "scan_attempts", "mode": "static", "type": "unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "time_between_scans", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "rejoin_interval", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "rejoin_retry_interval", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x20" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the rejoin/scan tuning parameters (scan attempts, time between scans, rejoin interval and rejoin retry interval, in seconds).",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.15.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.15.3.
- 5 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
- Note: in the PDF IC table attribute 4 (rejoin_interval) carries no explicit (static)/(dyn.) marker; it is recorded as static, consistent with the neighbouring rejoin parameters in this configuration-only IC.
