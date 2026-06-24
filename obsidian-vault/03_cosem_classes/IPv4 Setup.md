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
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "DL_reference",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "IP_address",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "multicast_IP_address",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "IP_options",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "subnet_mask",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 7,
      "name": "gateway_IP_address",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 8,
      "name": "use_DHCP_flag",
      "type": "boolean",
      "mandatory": true
    },
    {
      "attribute_id": 9,
      "name": "primary_DNS_address",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 10,
      "name": "secondary_DNS_address",
      "type": "double-long-unsigned",
      "mandatory": true
    }
  ],
  "methods": []
}
```

## Notes

