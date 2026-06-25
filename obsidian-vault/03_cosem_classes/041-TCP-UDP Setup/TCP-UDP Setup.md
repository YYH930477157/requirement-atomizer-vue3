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
      "name": "TCP_UDP_port",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 3,
      "name": "IP_reference",
      "type": "octet-string[6]",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 4,
      "name": "MSS",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static",
      "minimum": 40,
      "maximum": 65535,
      "default": 576
    },
    {
      "attribute_id": 5,
      "name": "nb_of_sim_conn",
      "type": "unsigned",
      "mandatory": true,
      "storage": "static",
      "minimum": 1
    },
    {
      "attribute_id": 6,
      "name": "inactivity_time_out",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static",
      "default": 180
    }
  ],
  "methods": [],
  "access_semantics": [
    "TCP_UDP_port defines the TCP/UDP or CoAP UDP endpoint port used by the physical device.",
    "IP_reference points to the IPv4 or IPv6 setup object that owns IP-layer address settings.",
    "MSS is advertised only in the initial TCP SYN and is not negotiated by this attribute."
  ],
  "behavior_notes": [
    "TCP-UDP setup models the TCP or UDP sub-layer for TCP-UDP/IP and CoAP communication profiles.",
    "Within a physical device, each client AP or server logical device is bound to a wrapper port with help from SAP Assignment.",
    "nb_of_sim_conn limits simultaneous TCP/UDP connections supported by the transport layer.",
    "inactivity_time_out aborts inactive TCP connections; zero disables this timeout."
  ],
  "common_instances": [
    {
      "name": "TCP-UDP setup for IPv4",
      "obis": "0-0:25.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.9.1 TCP-UDP setup (class_id = 41, version = 0)"
    }
  ]
}
```

## Notes

