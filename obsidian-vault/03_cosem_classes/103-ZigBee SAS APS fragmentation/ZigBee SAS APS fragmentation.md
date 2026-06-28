---
id: KB-L3-IC-103-ZIGBEE-SAS-APS-FRAGMENTATION
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ZigBee SAS APS fragmentation
aliases:
- class 103
- CL 103
keywords:
- zigbee sas aps fragmentation
- class 103
- cl 103
- logical_name
- aps_interframe_delay
- aps_max_window_size
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ZigBee SAS APS fragmentation

## Definition

COSEM interface class (class_id = 103, version = 0). Configures the fragmentation feature of the ZigBee® PRO transport layer, allowing an external manager (DLMS client) to set the fragmentation function.

## Aliases

- class 103
- CL 103

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the APS fragmentation tuning parameters: the interframe delay (ms) between blocks of a fragmented transmission and the maximum number of unacknowledged frames that can be transmitted consecutively.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 103,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "aps_interframe_delay", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "aps_max_window_size", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x10" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the APS fragmentation tuning parameters: the interframe delay (ms) between blocks of a fragmented transmission and the maximum number of unacknowledged frames that can be transmitted consecutively.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.15.4; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.15.4.
- 3 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
