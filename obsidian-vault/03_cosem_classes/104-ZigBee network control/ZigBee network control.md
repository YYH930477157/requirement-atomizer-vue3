---
id: KB-L3-IC-104-ZIGBEE-NETWORK-CONTROL
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ZigBee network control
aliases:
- class 104
- CL 104
keywords:
- zigbee network control
- class 104
- cl 104
- logical_name
- enable_disable_joining
- join_timeout
- active_devices
- register_device
- unregister_device
- unregister_all_devices
- backup_pan
- restore_pan
- identify_device
- remove_mirror
- update_network_key
- update_link_key
- create_pan
- remove_pan
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ZigBee network control

## Definition

COSEM interface class (class_id = 104, version = 0). Provides interaction between a DLMS client (head-end system) and a ZigBee® coordinator, e.g. when commissioning the installation. There is a single instance in any device that can act as a ZigBee® coordinator controlled by the DLMS client.

## Aliases

- class 104
- CL 104

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the joining flag and timeout and the list of active (authorised) devices; the methods drive the coordinator to register/unregister devices, manage PAN backup/restore, key updates and PAN create/remove.
- Specific methods: register_device (mandatory), unregister_device (mandatory), unregister_all_devices (optional), backup_PAN (optional), restore_PAN (optional), identify_device (optional), remove_mirror (optional), update_network_key (optional), update_link_key (optional), create_PAN (mandatory), remove_PAN (mandatory).

## Structured Data

```json metadata
{
  "class_id": 104,
  "version": 0,
  "cardinality": "0..1",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "enable_disable_joining", "mode": "static", "type": "boolean", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "join_timeout", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "active_devices", "mode": "dynamic", "type": "array", "short_name": "x + 0x18" }
  ],
  "methods": [
    { "method_id": 1, "name": "register_device", "short_name": "x + 0x20" },
    { "method_id": 2, "name": "unregister_device", "short_name": "x + 0x28" },
    { "method_id": 3, "name": "unregister_all_devices", "short_name": "x + 0x30" },
    { "method_id": 4, "name": "backup_PAN", "short_name": "x + 0x38" },
    { "method_id": 5, "name": "restore_PAN", "short_name": "x + 0x40" },
    { "method_id": 6, "name": "identify_device", "short_name": "x + 0x48" },
    { "method_id": 7, "name": "remove_mirror", "short_name": "x + 0x50" },
    { "method_id": 8, "name": "update_network_key", "short_name": "x + 0x58" },
    { "method_id": 9, "name": "update_link_key", "short_name": "x + 0x60" },
    { "method_id": 10, "name": "create_PAN", "short_name": "x + 0x68" },
    { "method_id": 11, "name": "remove_PAN", "short_name": "x + 0x70" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the joining flag and timeout and the list of active (authorised) devices; the methods drive the coordinator to register/unregister devices, manage PAN backup/restore, key updates and PAN create/remove.",
    "Specific methods: register_device (mandatory), unregister_device (mandatory), unregister_all_devices (optional), backup_PAN (optional), restore_PAN (optional), identify_device (optional), remove_mirror (optional), update_network_key (optional), update_link_key (optional), create_PAN (mandatory), remove_PAN (mandatory)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.15.5; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.15.5.
- 4 attributes, 11 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
- Note: cardinality is 0..1 (single instance per coordinator), as in the PDF IC table. In the PDF IC table attribute 2 (enable_disable_joining) carries no explicit (static)/(dyn.) marker; it is recorded as static (a configuration flag), consistent with its description.
