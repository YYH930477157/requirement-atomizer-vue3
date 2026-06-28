---
id: KB-L3-IC-153-COAP-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: CoAP diagnostic
aliases:
- class 153
- CL 153
keywords:
- coap diagnostic
- class 153
- cl 153
- logical_name
- messages_counter
- request_response_counter
- coap_bt_counter
- capture_time
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# CoAP diagnostic

## Definition

COSEM interface class (class_id = 153, version = 0). Holds information related to the DLMS/COSEM CoAP transport layer operation of a DLMS server.

## Aliases

- class 153
- CL 153

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the CoAP messaging counters, request/response counters and Block-Wise transfer counters, plus a capture_time timestamp of the most recent change; the reset method clears all counters and stamps capture_time with the reset time.
- Specific methods: reset (optional).

## Structured Data

```json metadata
{
  "class_id": 153,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "messages_counter", "mode": "dynamic", "type": "Structure", "short_name": "x + 0x10" },
    { "attribute_id": 3, "name": "request_response_counter", "mode": "dynamic", "type": "Structure", "short_name": "x + 0x18" },
    { "attribute_id": 4, "name": "coap_bt_counter", "mode": "dynamic", "type": "Structure", "short_name": "x + 0x20" },
    { "attribute_id": 5, "name": "capture_time", "mode": "dynamic", "type": "Structure", "short_name": "x + 0x28" }
  ],
  "methods": [
    { "method_id": 1, "name": "reset", "short_name": "x + 0x30" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the CoAP messaging counters, request/response counters and Block-Wise transfer counters, plus a capture_time timestamp of the most recent change; the reset method clears all counters and stamps capture_time with the reset time.",
    "Specific methods: reset (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.9.9; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.9.9.
- 5 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
- Note: in the PDF IC table attribute 2 (messages_counter) has short name x + 0x10 (not x + 0x08), as taken verbatim; attributes 2-5 are all of data type "Structure" as printed in the IC table.
