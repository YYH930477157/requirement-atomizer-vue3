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
- ntp server
- network time
- time synchronization
- synchronization interval
domain_tags:
- cosem_class
- communication_profile
- time_sync
- network_setup
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# NTP setup

## Definition

COSEM interface class for configuring Network Time Protocol synchronization parameters used by DLMS/COSEM devices.

## Aliases

- class 100
- CL 100
- NTP client setup
- network time protocol setup

## Domain Tags

- `cosem_class`
- `communication_profile`
- `time_sync`
- `network_setup`

## Structured Data

```json metadata
{
  "class_id": 100,
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
      "name": "activated",
      "type": "boolean",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Enables or disables NTP time synchronization"
    },
    {
      "attribute_id": 3,
      "name": "server_address",
      "type": "visible-string",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Configured NTP server address or host name"
    },
    {
      "attribute_id": 4,
      "name": "port",
      "type": "long-unsigned",
      "access": "R/W",
      "mandatory": true,
      "meaning": "UDP port used for NTP communication"
    },
    {
      "attribute_id": 5,
      "name": "authentication_method",
      "type": "enum",
      "access": "R/W",
      "mandatory": false,
      "meaning": "Authentication mode used for NTP packets when supported"
    },
    {
      "attribute_id": 6,
      "name": "authentication_keys",
      "type": "array",
      "access": "R/W",
      "mandatory": false,
      "meaning": "NTP authentication key material or key references"
    },
    {
      "attribute_id": 7,
      "name": "client_key",
      "type": "structure",
      "access": "R/W",
      "mandatory": false,
      "meaning": "Client key information used by authenticated NTP"
    }
  ],
  "methods": [],
  "access_semantics": [
    "activated, server_address, and port are management configuration attributes for network time synchronization.",
    "authentication_method, authentication_keys, and client_key are security-sensitive and should be writable only by authorized management clients.",
    "Read access to key material should be restricted or suppressed according to the security profile."
  ],
  "behavior_notes": [
    "Use this class when requirements mention NTP, network time synchronization, server address, UDP port 123, or authenticated time sync.",
    "NTP setup complements Clock class requirements: Clock stores meter time, while NTP setup defines how network time is obtained."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.50 NTP setup (class_id = 100, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with NTP activation, server, port, and authentication semantics."
}
```

## Notes

- Use this class to connect network time synchronization requirements to the Clock object and IP transport setup.
