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

COSEM interface class for IPv6 network setup parameters, including address configuration mode, IPv6 addresses, gateways, DNS addresses, and neighbor discovery related configuration.

## Aliases

- IPv6 setup object
- class 48
- CL 48

## Domain Tags

- `cosem_class`
- `communication_profile`
- `ip_network`

## Structured Data

```json metadata
{
  "class_id": 48,
  "version": 0,
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "mandatory": true},
    {"attribute_id": 2, "name": "DL_reference", "type": "octet-string[6]", "mandatory": true},
    {"attribute_id": 3, "name": "address_config_mode", "type": "enum", "mandatory": true},
    {"attribute_id": 4, "name": "unicast_IPv6_addresses", "type": "array", "mandatory": true},
    {"attribute_id": 5, "name": "multicast_IPv6_addresses", "type": "array", "mandatory": true},
    {"attribute_id": 6, "name": "gateway_IPv6_addresses", "type": "array", "mandatory": true},
    {"attribute_id": 7, "name": "primary_DNS_address", "type": "octet-string[16]", "mandatory": true},
    {"attribute_id": 8, "name": "secondary_DNS_address", "type": "octet-string[16]", "mandatory": true}
  ],
  "methods": [],
  "access_semantics": [
    "DL_reference links the IPv6 setup object to the lower-layer communication setup object.",
    "address_config_mode defines the IPv6 address configuration mechanism used by the device.",
    "unicast, multicast, gateway, and DNS address attributes describe the IPv6 network configuration visible through COSEM."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.9.3 IPv6 setup (class_id = 48, version = 0)"
    }
  ]
}
```

## Notes
