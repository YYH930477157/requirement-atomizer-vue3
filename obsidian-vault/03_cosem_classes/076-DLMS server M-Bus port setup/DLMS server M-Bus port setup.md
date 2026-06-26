---
id: KB-L3-IC-76-DLMS-SERVER-M-BUS-PORT-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: DLMS server M-Bus port setup
aliases:
- class 76
- CL 76
- dlms server m-bus port
- server side m-bus port setup
keywords:
- dlms server m-bus port setup
- class 76
- cl 76
- server m-bus communication
- server port setup
- m-bus server address
- m-bus server speed
domain_tags:
- cosem_class
- communication_profile
- m_bus
- port_setup
- server_port
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# DLMS server M-Bus port setup

## Definition

COSEM interface class for configuring DLMS server M-Bus port setup parameters in DLMS/COSEM devices.

## Aliases

- class 76
- CL 76
- dlms server m-bus port
- server side m-bus port setup

## Domain Tags

- `cosem_class`
- `communication_profile`
- `m_bus`
- `port_setup`
- `server_port`

## Structured Data

```json metadata
{
  "class_id": 76,
  "version": 0,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "access": "R",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "comm_speed",
      "type": "enum",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Communication speed used by the DLMS server M-Bus port"
    },
    {
      "attribute_id": 3,
      "name": "server_primary_address",
      "type": "unsigned",
      "access": "R/W",
      "mandatory": false,
      "meaning": "Primary address used when the DLMS server exposes itself through an M-Bus port"
    },
    {
      "attribute_id": 4,
      "name": "identification_number",
      "type": "double-long-unsigned",
      "access": "R/W",
      "mandatory": false,
      "meaning": "Identification number exposed through the server-side M-Bus port"
    }
  ],
  "methods": [],
  "access_semantics": [
    "comm_speed and server_primary_address affect external reachability through the M-Bus server port and require controlled write access.",
    "Identification values should be aligned with device identity and installation requirements.",
    "Server-side M-Bus port setup is distinct from M-Bus client configuration used to read attached slave devices."
  ],
  "behavior_notes": [
    "Use this class when requirements mention DLMS server access over M-Bus, server M-Bus primary address, or M-Bus port identity.",
    "Pair these requirements with association and communication profile requirements when external clients access the server through M-Bus."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.39 DLMS server M-Bus port setup (class_id = 76, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with server-side M-Bus speed, addressing, identity, and access semantics."
}
```

## Notes

- Do not confuse server-side M-Bus access with the client-side M-Bus capture object.
