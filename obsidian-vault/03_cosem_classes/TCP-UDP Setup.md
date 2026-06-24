---
id: KB-L3-IC-41-TCP-UDP-SETUP
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: TCP-UDP Setup
aliases:
- TCP UDP Setup
- class 41
- CL 41
keywords:
- class 41
- cl 41
- tcp-udp setup
- tcp udp setup
- port
- ip_reference
- mss
- nb_of_sim_conn
domain_tags:
- cosem_class
- communication_profile
- ip_network
---

# TCP-UDP Setup

## Definition

COSEM class for TCP/UDP transport setup parameters.

## Aliases

- TCP UDP Setup
- class 41
- CL 41

## Domain Tags

- `cosem_class`
- `communication_profile`
- `ip_network`

## Structured Data

```json metadata
{
  "class_id": 41,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "TCP_UDP_port",
      "type": "long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "IP_reference",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "MSS",
      "type": "long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "nb_of_sim_conn",
      "type": "unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "inactivity_time_out",
      "type": "long-unsigned",
      "mandatory": true
    }
  ],
  "methods": []
}
```

## Notes

