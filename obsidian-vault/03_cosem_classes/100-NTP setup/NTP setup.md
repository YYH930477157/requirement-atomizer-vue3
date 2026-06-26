---
id: KB-L3-IC-100-NTP-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: NTP setup
aliases:
- class 100
- CL 100
- NTP client setup
- network time protocol setup
keywords:
- ntp setup
- class 100
- cl 100
- activated
- server_address
- server_port
- authentication_method
- authentication_keys
- client_key
- synchronize
- ntp server
- network time
- time synchronization
- synchronization interval
domain_tags:
- cosem_class
- communication_profile
- ntp
- time_sync
- network_setup
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# NTP setup

## Definition

COSEM interface class (class_id = 100, version = 0) for setting up time synchronisation using the NTP protocol as specified in RFC 5905. One or several instances may be configured to support multiple time servers. Cardinality 0...n.

## Aliases

- class 100
- CL 100
- NTP client setup
- network time protocol setup

## Domain Tags

- `cosem_class`
- `communication_profile`
- `ntp`
- `time_sync`
- `network_setup`

## Access Semantics

All attributes are **static**, read-write (RW) via the SET service by an authorised management client. logical_name is read-only for all clients. authentication_keys and client_key are sensitive cryptographic material that must be protected.

## Behavior Notes

- NTP setup allows time synchronisation via the NTP protocol (RFC 5905). One or several instances support multiple time servers. Cardinality 0...n.
- **activated** (attr 2): boolean, TRUE = synchronisation active, FALSE = inactive. Default FALSE.
- **server_address** (attr 3): NTP server address as octet-string. DNS-resolvable name, or IPv4 dotted-decimal (163.187.45.87), or IPv6 text (2001:db8::1:0:0:1).
- **server_port** (attr 4): UDP port for NTP. Default 123 (IANA ntp 123/udp).
- **authentication_method** (attr 5): enum defining the NTP authentication mode.
- **authentication_keys** (attr 6): array of authentication keys (sensitive).
- **client_key** (attr 7): client key octet-string (sensitive).

## Methods

- **synchronize** (method 1): trigger NTP time synchronisation (param: data). Mandatory.
- **add_authentication_key** (method 2): add one NTP authentication key (param: data). Optional.
- **delete_authentication_key** (method 3): delete one NTP authentication key (param: data). Optional.

## Structured Data

```json metadata
{
  "class_id": 100,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "activated", "type": "boolean", "static": true, "mandatory": true, "access_rights": "RW", "default": false, "short_name": "0x08"},
    {"attribute_id": 3, "name": "server_address", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "server_port", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "default": 123, "short_name": "0x18"},
    {"attribute_id": 5, "name": "authentication_method", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x20"},
    {"attribute_id": 6, "name": "authentication_keys", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x28"},
    {"attribute_id": 7, "name": "client_key", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x30"}
  ],
  "methods": [
    {"method_id": 1, "name": "synchronize", "parameter_type": "data", "mandatory": true, "short_name": "0x38", "meaning": "Trigger NTP time synchronisation."},
    {"method_id": 2, "name": "add_authentication_key", "parameter_type": "data", "mandatory": false, "short_name": "0x40", "meaning": "Add one NTP authentication key."},
    {"method_id": 3, "name": "delete_authentication_key", "parameter_type": "data", "mandatory": false, "short_name": "0x48", "meaning": "Delete one NTP authentication key."}
  ],
  "access_semantics": [
    "All attributes are static, read-write (RW) via SET by an authorised management client; logical_name read-only for all.",
    "activated toggles NTP synchronisation on/off (default FALSE).",
    "server_address may be DNS name, IPv4 dotted-decimal, or IPv6 text.",
    "authentication_keys and client_key are sensitive cryptographic material."
  ],
  "behavior_notes": [
    "NTP setup allows time synchronisation via NTP (RFC 5905). Cardinality 0...n; multiple instances support multiple time servers.",
    "activated: boolean, TRUE = sync active, default FALSE.",
    "server_port: default 123 (IANA ntp 123/udp).",
    "synchronize method triggers synchronisation; add/delete_authentication_key manage auth keys.",
    "authentication_method: enum defining NTP authentication mode."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.9.7 NTP setup (class_id = 100, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.9.7. Full attributes with access_rights, methods with semantics, value defaults, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.9.7 (page 300-301).
- NTP protocol per RFC 5905. IANA NTP port: ntp 123/udp.
- Use this class to connect network time synchronization requirements to the Clock object and IP transport setup.
