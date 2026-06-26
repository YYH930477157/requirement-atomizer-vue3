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
- inactivity_time_out
domain_tags:
- cosem_class
- communication_profile
- ip_network
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# TCP-UDP Setup

## Definition

COSEM interface class (class_id = 41, version = 0) for modelling the setup of the TCP or UDP sub-layer of the COSEM TCP/UDP based transport layer (TCP-UDP/IP profile) or the UDP sub-layer of the DLMS/COSEM CoAP transport layer. Cardinality 0...n.

## Aliases

- TCP UDP Setup
- class 41
- CL 41

## Domain Tags

- `cosem_class`
- `communication_profile`
- `ip_network`

## Access Semantics

All attributes are **static**, read-write (RW) via the SET service by an authorised management client. logical_name is read-only for all clients. The configuration governs the TCP/UDP transport sub-layer; each AP (client AP or server logical device) is bound to a wrapper port via the SAP Assignment object.

## Behavior Notes

- TCP-UDP setup models the TCP or UDP sub-layer for TCP-UDP/IP and CoAP communication profiles. Cardinality 0...n; one instance per data link layer (e.g. Ethernet, PPP).
- **TCP-UDP_port** (attr 2): port number on which the physical device listens for DLMS/COSEM (IANA-registered 4059/TCP and 4059/UDP), or the UDP port of the CoAP endpoint.
- **IP_reference** (attr 3): references the IPv4/IPv6 setup object by logical name that owns the IP-layer address settings.
- **MSS** (attr 4): Maximum Segment Size. Range 40-65535, default 576. Advertised only in the initial TCP SYN; not negotiable by this attribute.
- **nb_of_sim_conn** (attr 5): max simultaneous TCP/UDP connections supported by the transport layer. Min 1.
- **inactivity_time_out** (attr 6): time in seconds after which an inactive TCP connection is aborted; 0 = never aborted (not operational). Default 180.

## Structured Data

```json metadata
{
  "class_id": 41,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "TCP-UDP_port", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x08"},
    {"attribute_id": 3, "name": "IP_reference", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "MSS", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 40, "max": 65535, "default": 576, "short_name": "0x18"},
    {"attribute_id": 5, "name": "nb_of_sim_conn", "type": "unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 1, "short_name": "0x20"},
    {"attribute_id": 6, "name": "inactivity_time_out", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "default": 180, "short_name": "0x28"}
  ],
  "methods": [],
  "access_semantics": [
    "All attributes are static, read-write (RW) via SET by an authorised management client; logical_name is read-only.",
    "TCP-UDP_port defines the TCP/UDP or CoAP UDP endpoint port (IANA 4059) used by the physical device.",
    "IP_reference points to the IPv4 or IPv6 setup object that owns IP-layer address settings.",
    "MSS is advertised only in the initial TCP SYN and is not negotiated by this attribute."
  ],
  "behavior_notes": [
    "TCP-UDP setup models the TCP or UDP sub-layer for TCP-UDP/IP and CoAP profiles. Cardinality 0...n; one instance per data link layer.",
    "Within a physical device, each client AP or server logical device is bound to a wrapper port with help from SAP Assignment.",
    "nb_of_sim_conn limits simultaneous TCP/UDP connections supported by the transport layer.",
    "inactivity_time_out aborts inactive TCP connections; zero disables this timeout."
  ],
  "common_instances": [
    {"name": "TCP-UDP setup for IPv4", "obis": "0-0:25.0.0.255"}
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.9.1 TCP-UDP setup (class_id = 41, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.9.1. Full attributes with access_rights, value ranges, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.9.1 (page 286-287).
- IANA-registered ports: dlms/cosem 4059/TCP and 4059/UDP.
