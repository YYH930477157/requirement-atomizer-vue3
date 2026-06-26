---
id: KB-L3-IC-19-IEC-LOCAL-PORT-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: IEC local port setup
aliases:
- class 19
- CL 19
- IEC 62056-21 local port
keywords:
- iec local port setup
- optical port
- local port baud rate
- default mode
- proposed baudrate
- class 19
- cl 19
- default_mode
- default_baud
- prop_baud
- response_time
- device_addr
- pass_p1
- pass_p2
- pass_w5
domain_tags:
- cosem_class
- communication_profile
- iec_local_port
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IEC local port setup

## Definition

COSEM interface class (class_id = 19, version = 1) for configuring communication ports using the protocols specified in IEC 62056-21:2002. Allows modelling the configuration of the local (optical/electrical) port of a DLMS/COSEM device. Several ports can be configured (0...n instances).

## Aliases

- class 19
- CL 19
- IEC 62056-21 local port

## Domain Tags

- `cosem_class`
- `communication_profile`
- `iec_local_port`

## Access Semantics

All attributes are **static** (marked `(static)` in the Blue Book IC definition). Static attributes are set during manufacturing/configuration and are read-write (RW) via the SET service by an authorised client (typically a management client). They are not writable via the public/read client. The default access rights follow the COSEM access model: logical_name is read-only for all; configuration attributes are RW for management clients, read-only for operational clients.

## Behavior Notes

- **Protocol selection**: `default_mode` (attribute 2) selects the protocol used on the port. enum (0) = IEC 62056-21:2002 modes A-E; (1) = IEC 62056-46:2002/AMD1:2006 (when selected, all other attributes except logical_name and prop_baud are not applicable); (2) = protocol not specified (then attribute 4 prop_baud sets the speed, all others not applicable).
- **Baud rate negotiation**: `default_baud` (attr 3) is the opening-sequence baud rate; `prop_baud` (attr 4) is the baud rate proposed by the meter after the opening sequence. enum range 0-9 maps to 300/600/1200/2400/4800/9600/19200/38400/57600/115200 baud.
- **Response timing**: `response_time` (attr 5) defines the minimum delay between end of request and start of response. enum (0) = 20 ms, (1) = 200 ms.
- **Security**: `pass_p1` (attr 7) and `pass_p2` (attr 8) are passwords per IEC 62056-21:2002; `pass_w5` (attr 9) is reserved for national applications. These are sensitive and must be protected.
- **No specific methods**: This IC defines no methods; configuration is done entirely via SET on the static attributes.

## Structured Data

```json metadata
{
  "class_id": 19,
  "version": 1,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "default_mode", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x08"},
    {"attribute_id": 3, "name": "default_baud", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "prop_baud", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x18"},
    {"attribute_id": 5, "name": "response_time", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x20"},
    {"attribute_id": 6, "name": "device_addr", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x28"},
    {"attribute_id": 7, "name": "pass_p1", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x30"},
    {"attribute_id": 8, "name": "pass_p2", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x38"},
    {"attribute_id": 9, "name": "pass_w5", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x40"}
  ],
  "methods": [],
  "enum_definitions": {
    "default_mode": {"0": "IEC 62056-21:2002 modes A-E", "1": "IEC 62056-46:2002/AMD1:2006", "2": "protocol not specified"},
    "default_baud": {"0": "300", "1": "600", "2": "1200", "3": "2400", "4": "4800", "5": "9600", "6": "19200", "7": "38400", "8": "57600", "9": "115200"},
    "response_time": {"0": "20 ms", "1": "200 ms"}
  },
  "access_semantics": [
    "All attributes are static, read-write (RW) via SET by an authorised management client; logical_name read-only for all.",
    "default_mode selects the port protocol; when (1) or (2) is selected, most other attributes become not applicable.",
    "pass_p1/pass_p2/pass_w5 are sensitive passwords per IEC 62056-21 and must be protected."
  ],
  "behavior_notes": [
    "IEC local port setup configures communication ports per IEC 62056-21:2002. Cardinality 0...n.",
    "default_mode: enum (0) IEC 62056-21 modes A-E, (1) IEC 62056-46, (2) unspecified; (1)/(2) make most attributes N/A.",
    "default_baud/prop_baud: enum 0-9 maps to 300...115200 baud.",
    "response_time: enum (0) 20 ms, (1) 200 ms.",
    "No specific methods; configuration via SET on static attributes.",
    "Use this class when a requirement mentions local optical-port setup, IEC local port baud rates, IEC response time, or local-port passwords.",
    "Treat password attributes as credential material even when source documents list them alongside ordinary communication parameters."
  ],
  "common_instances": [
    {"name": "IEC local port setup", "obis_pattern": "0-0:20.0.0.255"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-25 from Blue Book Part 2 Ed.16 section 4.7.1. Full attributes with access_rights, enum definitions, access_semantics, and behavior_notes."
}
```

## Notes

- Use this class when a requirement mentions local optical-port setup, IEC local port baud rates, IEC response time, or local-port passwords.
- Treat password attributes as credential material even when source documents list them alongside ordinary communication parameters.
- Source: Blue Book Part 2 Ed.16, section 4.7.1 (page 248-249).
- Instance cardinality 0...n: multiple local ports can be configured.
