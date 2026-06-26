---
id: KB-L3-IC-23-IEC-HDLC-SETUP
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: IEC HDLC Setup
aliases:
- class 23
- CL 23
- HDLC setup
keywords:
- class 23
- cl 23
- iec hdlc setup
- comm_speed
- window_size_transmit
- window_size_receive
- max_info_field_length_transmit
- max_info_field_length_receive
- inter_octet_time_out
- inactivity_time_out
- device_address
domain_tags:
- cosem_class
- communication_profile
- hdlc
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IEC HDLC Setup

## Definition

COSEM interface class (class_id = 23, version = 1) for modelling and configuring communication channels according to DLMS UA 1000-2 Ed.11:2021 Clause 8 and IEC 62056-46:2007. Several communication channels can be configured (0...n instances).

## Aliases

- class 23
- CL 23
- HDLC setup

## Domain Tags

- `cosem_class`
- `communication_profile`
- `hdlc`

## Access Semantics

All attributes are **static** channel configuration parameters, read-write (RW) via the SET service by an authorised management client. logical_name is read-only for all clients. Window sizes and maximum information field lengths may be negotiated to smaller values during logon. comm_speed enumerates 300 through 115200 baud values and may be overridden by entering HDLC mode through another protocol.

## Behavior Notes

- IEC HDLC setup configures one communication channel per IEC 62056-46. Cardinality 0...n.
- **comm_speed** (attr 2): supported port speed, enum 0-9 → 300/600/1200/2400/4800/9600(default)/19200/38400/57600/115200.
- **window_size_transmit/receive** (attr 3/4): max frames sent/received before ACK required, range 1-7, default 1, negotiable during logon.
- **max_info_field_length_transmit/receive** (attr 5/6): max info field length in bytes, range 32-2030, default 128. NOTE: max raised 128→2030 for efficiency; 128 needed for minimal performance.
- **inter_octet_time_out** (attr 7): time in ms over which, with no character received, received data is treated as a complete frame. Range 20-6000, default 25. NOTE: max raised 1000→6000 for long-delay media.
- **inactivity_time_out** (attr 8): time in seconds after which no frame received triggers disconnection; 0 = not operational. Range 0-120.
- **device_address** (attr 9): physical HDLC address. One-byte addressing: 0x00=NO_STATION, 0x01-0x0F reserved, 0x10-0x7D usable, 0x7E=CALLING, 0x7F=broadcast.

## Structured Data

```json metadata
{
  "class_id": 23,
  "version": 1,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "comm_speed", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "min": 0, "max": 9, "default": 5, "short_name": "0x08"},
    {"attribute_id": 3, "name": "window_size_transmit", "type": "unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 1, "max": 7, "default": 1, "short_name": "0x10"},
    {"attribute_id": 4, "name": "window_size_receive", "type": "unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 1, "max": 7, "default": 1, "short_name": "0x18"},
    {"attribute_id": 5, "name": "max_info_field_length_transmit", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 32, "max": 2030, "default": 128, "short_name": "0x20"},
    {"attribute_id": 6, "name": "max_info_field_length_receive", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 32, "max": 2030, "default": 128, "short_name": "0x28"},
    {"attribute_id": 7, "name": "inter_octet_time_out", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 20, "max": 6000, "default": 25, "short_name": "0x30"},
    {"attribute_id": 8, "name": "inactivity_time_out", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 0, "max": 120, "short_name": "0x38"},
    {"attribute_id": 9, "name": "device_address", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "min": 0, "max": 1023, "default": 16, "short_name": "0x40"}
  ],
  "methods": [],
  "enum_definitions": {
    "comm_speed": {"0": "300", "1": "600", "2": "1200", "3": "2400", "4": "4800", "5": "9600", "6": "19200", "7": "38400", "8": "57600", "9": "115200"}
  },
  "access_semantics": [
    "All attributes are static channel configuration parameters, read-write (RW) via SET by an authorised management client.",
    "logical_name is read-only for all clients.",
    "comm_speed enumerates 300 through 115200 baud values and may be overridden by entering HDLC mode through another protocol.",
    "window sizes and maximum information field lengths may be negotiated to smaller values during logon."
  ],
  "behavior_notes": [
    "IEC HDLC setup configures one communication channel per IEC 62056-46. Cardinality 0...n.",
    "comm_speed: enum 0-9 maps to 300...115200 baud; default 5 (9600).",
    "window_size_transmit/receive: range 1-7, default 1, negotiable during logon.",
    "max_info_field_length_transmit/receive: range 32-2030 bytes, default 128; max raised from 128 for efficiency.",
    "inter_octet_time_out: range 20-6000 ms, default 25; max raised from 1000 for long-delay media.",
    "inactivity_time_out: range 0-120 s; 0 disables disconnection processing.",
    "device_address: one-byte addressing, 0x10-0x7D usable, 0x7E calling, 0x7F broadcast."
  ],
  "common_instances": [
    {"name": "IEC HDLC setup", "obis": "0-0:22.0.0.255"}
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.7.2 IEC HDLC setup (class_id = 23, version = 1)"},
    {"source": "Blue Book Part 2 Ed. 16", "section": "5.7.2 IEC HDLC setup (class_id = 23, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-25 from Blue Book Part 2 Ed.16 section 4.7.2. Full attributes with access_rights, value ranges, enum definitions, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.7.2 (page 250-251).
- Instance cardinality 0...n: multiple HDLC channels can be configured.
- max_info_field_length max increased 128 -> 2030 for efficiency; inter_octet_time_out max increased 1000 -> 6000 ms for long-delay media.
