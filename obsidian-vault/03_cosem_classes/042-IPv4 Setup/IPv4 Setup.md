---
id: KB-L3-IC-42-IPV4-SETUP
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: IPv4 Setup
aliases:
- class 42
- CL 42
keywords:
- class 42
- cl 42
- ipv4 setup
- ip_address
- multicast_ip_address
- gateway_ip_address
- subnet_mask
- dl_reference
- use_dhcp_flag
- primary_dns_address
domain_tags:
- cosem_class
- communication_profile
- ip_network
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IPv4 Setup

## Definition

COSEM interface class (class_id = 42, version = 0) for modelling the setup of the IPv4 layer, handling all information related to the IP address settings of a given device and lower layer connection. There shall be one instance per network interface implemented (cardinality 0...n).

## Aliases

- class 42
- CL 42

## Domain Tags

- `cosem_class`
- `communication_profile`
- `ip_network`

## Access Semantics

logical_name and the static configuration attributes (DL_reference, use_DHCP_flag) are read-write (RW) via SET by an authorised management client; logical_name is read-only for all. The dynamic address attributes (IP_address, multicast_IP_address, subnet_mask, gateway_IP_address, primary/secondary_DNS_address) may be assigned statically (RW) or dynamically via DHCP; their access_rights are RW but runtime values may reflect DHCP negotiation when use_DHCP_flag is true.

## Behavior Notes

- A device has one IPv4 setup instance per network interface using TCP-UDP/IPv4. Cardinality 0...n.
- **DL_reference** (attr 2): references the data link layer (e.g. Ethernet/PPP) setup object by logical name.
- **IP_address** (attr 3): IPv4 address as double-long-unsigned. Static or dynamic (DHCP); 0 = no address assigned. Example: 192.168.0.1 = C0A80001 hex = 3232235521.
- **multicast_IP_address** (attr 4): array of class-D multicast addresses (224.0.0.0 - 239.255.255.255) the device accepts. Managed via methods add_mc/delete_mc/get_nbof.
- **subnet_mask** (attr 6) / **gateway_IP_address** (attr 7): network parameters.
- **use_DHCP_flag** (attr 8): boolean, enables dynamic IP assignment via DHCP.
- **primary/secondary_DNS_address** (attr 9/10): DNS resolver addresses.
- **IP_options** (attr 5): may carry RFC 791 options (security, source route, record route, internet timestamp).

## Methods

- **add_mc_IP_address** (method 1): add one multicast IPv4 address (param: double-long-unsigned).
- **delete_mc_IP_address** (method 2): delete one multicast IPv4 address (param: double-long-unsigned).
- **get_nbof_mc_IP_addresses** (method 3): return count of configured multicast addresses.

## Structured Data

```json metadata
{
  "class_id": 42,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "DL_reference", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x08"},
    {"attribute_id": 3, "name": "IP_address", "type": "double-long-unsigned", "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "multicast_IP_address", "type": "array", "mandatory": true, "access_rights": "RW", "short_name": "0x18"},
    {"attribute_id": 5, "name": "IP_options", "type": "array", "mandatory": true, "access_rights": "RW", "short_name": "0x20"},
    {"attribute_id": 6, "name": "subnet_mask", "type": "double-long-unsigned", "mandatory": true, "access_rights": "RW", "short_name": "0x28"},
    {"attribute_id": 7, "name": "gateway_IP_address", "type": "double-long-unsigned", "mandatory": true, "access_rights": "RW", "short_name": "0x30"},
    {"attribute_id": 8, "name": "use_DHCP_flag", "type": "boolean", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x38"},
    {"attribute_id": 9, "name": "primary_DNS_address", "type": "double-long-unsigned", "mandatory": true, "access_rights": "RW", "short_name": "0x40"},
    {"attribute_id": 10, "name": "secondary_DNS_address", "type": "double-long-unsigned", "mandatory": true, "access_rights": "RW", "short_name": "0x48"}
  ],
  "methods": [
    {"method_id": 1, "name": "add_mc_IP_address", "parameter_type": "double-long-unsigned", "short_name": "0x60", "meaning": "Add one multicast IPv4 address."},
    {"method_id": 2, "name": "delete_mc_IP_address", "parameter_type": "double-long-unsigned", "short_name": "0x68", "meaning": "Delete one multicast IPv4 address."},
    {"method_id": 3, "name": "get_nbof_mc_IP_addresses", "parameter_type": "integer(0)", "short_name": "0x70", "meaning": "Return the number of configured multicast IPv4 addresses."}
  ],
  "access_semantics": [
    "logical_name and static config attributes (DL_reference, use_DHCP_flag) are RW via SET by management client; logical_name read-only for all.",
    "Dynamic address attributes (IP_address, multicast, subnet_mask, gateway, DNS) are RW but runtime values may reflect DHCP negotiation when use_DHCP_flag is true.",
    "DL_reference points to the lower data-link setup object used by this IPv4 interface.",
    "multicast_IP_address holds class-D multicast addresses (224.0.0.0 - 239.255.255.255) accepted by the device."
  ],
  "behavior_notes": [
    "A device has one IPv4 setup instance per network interface using TCP-UDP/IPv4. Cardinality 0...n.",
    "IPv4 addresses are encoded as double-long-unsigned, e.g. 192.168.0.1 = C0A80001 = 3232235521.",
    "IP_address may be static or dynamic (DHCP); 0 means no address assigned.",
    "IP_options may carry RFC 791 options (security, source route, record route, internet timestamp)."
  ],
  "common_instances": [
    {"name": "IPv4 setup", "obis": "0-0:25.1.0.255"}
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.9.2 IPv4 setup (class_id = 42, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.9.2. Full attributes with access_rights, method behavior, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.9.2 (page 287-288).
- One instance per network interface (Ethernet, PPP, etc.).
