---
id: KB-L3-IC-48-IPV6-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: IPv6 Setup
aliases:
- IPv6 setup object
- class 48
- CL 48
keywords:
- ipv6 setup
- class 48
- cl 48
- address_config_mode
- unicast_ipv6_addresses
- multicast_ipv6_addresses
- gateway_ipv6_addresses
- primary_dns_address
- secondary_dns_address
- traffic_class
- neighbor discovery
- address configuration
domain_tags:
- cosem_class
- communication_profile
- ip_network
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IPv6 Setup

## Definition

COSEM interface class (class_id = 48, version = 0) for modelling the setup of the IPv6 layer, handling all information related to the IPv6 address settings of a given device and lower layer connection. One instance per network interface (cardinality 0...n).

## Aliases

- IPv6 setup object
- class 48
- CL 48

## Domain Tags

- `cosem_class`
- `communication_profile`
- `ip_network`

## Access Semantics

logical_name is read-only for all clients. The static configuration attributes (DL_reference, address_config_mode, multicast/gateway/DNS/traffic_class/neighbor_discovery) are read-write (RW) via SET by an authorised management client. unicast_IPv6_addresses is managed via the add/remove methods rather than direct SET. address_config_mode is common for all IPv6 addresses managed by one instance.

## Behavior Notes

- A device has one IPv6 setup instance per network interface. Cardinality 0...n.
- **address_config_mode** (attr 3): enum (0) Auto-configuration [default], (1) DHCPv6, (2) Manual, (3) ND (Neighbour Discovery). Common for all addresses of this instance.
- **unicast_IPv6_addresses** (attr 4): array of octet-string, RFC 3513 format. Static or dynamic. Empty array = no address (default) or reset all. Managed via add_IPv6_address/remove_IPv6_address methods.
- **multicast_IPv6_addresses** (attr 5): array of multicast IPv6 addresses; empty array = none/reset.
- **gateway_IPv6_addresses** (attr 6): array, default empty.
- **primary/secondary_DNS_address** (attr 7/8): octet-string, default 0.
- **traffic_class** (attr 9): unsigned, range 0-63, default 0.
- **neighbor_discovery_setup** (attr 10): static array of neighbour discovery parameters.

## Methods

- **add_IPv6_address** (method 1): add one IPv6 address (param: data).
- **remove_IPv6_address** (method 2): remove one IPv6 address (param: data).

## Structured Data

```json metadata
{
  "class_id": 48,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "DL_reference", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x08"},
    {"attribute_id": 3, "name": "address_config_mode", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "default": 0, "short_name": "0x10"},
    {"attribute_id": 4, "name": "unicast_IPv6_addresses", "type": "array", "mandatory": true, "access_rights": "RW", "short_name": "0x18"},
    {"attribute_id": 5, "name": "multicast_IPv6_addresses", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "default": [], "short_name": "0x20"},
    {"attribute_id": 6, "name": "gateway_IPv6_addresses", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "default": [], "short_name": "0x28"},
    {"attribute_id": 7, "name": "primary_DNS_address", "type": "octet-string[16]", "static": true, "mandatory": true, "access_rights": "RW", "default": 0, "short_name": "0x30"},
    {"attribute_id": 8, "name": "secondary_DNS_address", "type": "octet-string[16]", "static": true, "mandatory": true, "access_rights": "RW", "default": 0, "short_name": "0x38"},
    {"attribute_id": 9, "name": "traffic_class", "type": "unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 0, "max": 63, "default": 0, "short_name": "0x40"},
    {"attribute_id": 10, "name": "neighbor_discovery_setup", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x48"}
  ],
  "methods": [
    {"method_id": 1, "name": "add_IPv6_address", "parameter_type": "data", "short_name": "0x60", "meaning": "Add one IPv6 address."},
    {"method_id": 2, "name": "remove_IPv6_address", "parameter_type": "data", "short_name": "0x68", "meaning": "Remove one IPv6 address."}
  ],
  "enum_definitions": {
    "address_config_mode": {"0": "Auto-configuration (default)", "1": "DHCPv6", "2": "Manual", "3": "ND (Neighbour Discovery)"}
  },
  "access_semantics": [
    "logical_name is read-only for all clients; static config attributes are RW via SET by management client.",
    "DL_reference links the IPv6 setup object to the lower-layer communication setup object.",
    "address_config_mode defines the IPv6 address configuration mechanism (auto/DHCPv6/manual/ND); common for all addresses of this instance.",
    "unicast_IPv6_addresses is managed via add/remove methods; empty array = no address or reset."
  ],
  "behavior_notes": [
    "A device has one IPv6 setup instance per network interface. Cardinality 0...n.",
    "address_config_mode: enum 0=auto-config (default), 1=DHCPv6, 2=Manual, 3=ND.",
    "unicast/multicast/gateway IPv6 addresses follow RFC 3513 format; empty array resets all.",
    "traffic_class: range 0-63, default 0.",
    "neighbor_discovery_setup holds ND parameters."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.9.3 IPv6 setup (class_id = 48, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.9.3. Full attributes with access_rights, methods, value ranges, enum definitions, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.9.3 (page 291-292). See also Annex C.
- IPv6 address format per RFC 3513.
