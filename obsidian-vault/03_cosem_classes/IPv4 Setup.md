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
domain_tags:
- cosem_class
- communication_profile
- ip_network
---

# IPv4 Setup

## Definition

COSEM class for IPv4 network setup parameters.

## Aliases

- class 42
- CL 42

## Domain Tags

- `cosem_class`
- `communication_profile`
- `ip_network`

## Structured Data

```json metadata
{
  "class_id": 42,
  "version": 0,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 2,
      "name": "DL_reference",
      "type": "octet-string[6]",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 3,
      "name": "IP_address",
      "type": "double-long-unsigned",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 4,
      "name": "multicast_IP_address",
      "type": "array",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 5,
      "name": "IP_options",
      "type": "array",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 6,
      "name": "subnet_mask",
      "type": "double-long-unsigned",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 7,
      "name": "gateway_IP_address",
      "type": "double-long-unsigned",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 8,
      "name": "use_DHCP_flag",
      "type": "boolean",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 9,
      "name": "primary_DNS_address",
      "type": "double-long-unsigned",
      "mandatory": true,
      "storage": "dynamic"
    },
    {
      "attribute_id": 10,
      "name": "secondary_DNS_address",
      "type": "double-long-unsigned",
      "mandatory": true,
      "storage": "dynamic"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "add_mc_IP_address",
      "parameter_type": "double-long-unsigned",
      "meaning": "Add one multicast IPv4 address."
    },
    {
      "method_id": 2,
      "name": "delete_mc_IP_address",
      "parameter_type": "double-long-unsigned",
      "meaning": "Delete one multicast IPv4 address."
    },
    {
      "method_id": 3,
      "name": "get_nbof_mc_IP_addresses",
      "parameter_type": "integer(0)",
      "meaning": "Return the number of configured multicast IPv4 addresses."
    }
  ],
  "access_semantics": [
    "DL_reference points to the lower data-link setup object used by this IPv4 interface.",
    "IP_address may be static or dynamic; when no address is assigned the value is zero.",
    "multicast_IP_address holds class-D multicast addresses accepted by the device.",
    "use_DHCP_flag controls dynamic IP assignment, while DNS and gateway attributes hold resulting network parameters."
  ],
  "behavior_notes": [
    "A device has one IPv4 setup instance for each network interface that uses TCP-UDP/IPv4.",
    "IPv4 addresses are encoded as double-long-unsigned values, for example 192.168.0.1 as C0A80001.",
    "IP_options may carry RFC 791 options such as security, source route, record route, or internet timestamp."
  ],
  "common_instances": [
    {
      "name": "IPv4 setup",
      "obis": "0-0:25.1.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.9.2 IPv4 setup (class_id = 42, version = 0)"
    }
  ]
}
```

## Notes

