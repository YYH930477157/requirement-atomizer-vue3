---
id: KB-L3-IC-124-COMMUNICATION-PORT-PROTECTION
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Communication port protection
aliases:
- class 124
- CL 124
keywords:
- communication port protection
- class 124
- cl 124
- logical_name
- protection_mode
- allowed_failed_attempts
- initial_lockout_time
- steepness_factor
- max_lockout_time
- port_reference
- protection_status
- failed_attempts
- cumulative_failed_attempts
- reset
domain_tags:
- cosem_class
- communication_profile
- access_control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Communication port protection

## Definition

COSEM interface class (class_id = 124, version = 0). Protects communication ports of DLMS servers against possibly malicious communication attempts, in particular to prevent brute force attacks by reducing the possible number of attempts. Each instance references a single communication port; if an acceptable number of failed attempts is exceeded the port is temporarily locked, with the lockout time increasing up to a maximum.

## Aliases

- class 124
- CL 124

## Domain Tags

- `cosem_class`
- `communication_profile`
- `access_control`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the lockout policy (mode, allowed failed attempts, initial/max lockout time, steepness factor) and the runtime status (protection status, failed attempts and cumulative failed attempts); cumulative_failed_attempts is never reset.
- The reset method clears failed_attempts and the current lockout time, and sets protection_status to unlocked when the mode is locked_on_failed_attempts.
- Specific methods: reset (optional).

## Structured Data

```json metadata
{
  "class_id": 124,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "protection_mode", "mode": "static", "type": "enum", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "allowed_failed_attempts", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "initial_lockout_time", "mode": "static", "type": "double-long-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "steepness_factor", "mode": "static", "type": "unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "max_lockout_time", "mode": "static", "type": "double-long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "port_reference", "mode": "static", "type": "octet-string", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "protection_status", "mode": "dynamic", "type": "enum", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "failed_attempts", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "cumulative_failed_attempts", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x48" }
  ],
  "methods": [
    { "method_id": 1, "name": "reset", "short_name": "x + 0x50" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the lockout policy (mode, allowed failed attempts, initial/max lockout time, steepness factor) and the runtime status (protection status, failed attempts and cumulative failed attempts); cumulative_failed_attempts is never reset.",
    "The reset method clears failed_attempts and the current lockout time, and sets protection_status to unlocked when the mode is locked_on_failed_attempts.",
    "Specific methods: reset (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.4.12; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.4.12.
- 10 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
