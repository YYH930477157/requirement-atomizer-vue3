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
keywords:
- class 23
- cl 23
- iec hdlc setup
- communication_speed
- window_size_transmit
- window_size_receive
domain_tags:
- cosem_class
- communication_profile
- hdlc
---

# IEC HDLC Setup

## Definition

COSEM class for IEC HDLC communication setup parameters.

## Aliases

- class 23
- CL 23

## Domain Tags

- `cosem_class`
- `communication_profile`
- `hdlc`

## Structured Data

```json metadata
{
  "class_id": 23,
  "version": 1,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "comm_speed",
      "type": "enum",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 3,
      "name": "window_size_transmit",
      "type": "unsigned",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 4,
      "name": "window_size_receive",
      "type": "unsigned",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 5,
      "name": "max_info_field_length_transmit",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 6,
      "name": "max_info_field_length_receive",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 7,
      "name": "inter_octet_time_out",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 8,
      "name": "inactivity_time_out",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 9,
      "name": "device_address",
      "type": "long-unsigned",
      "mandatory": true,
      "storage": "static"
    }
  ],
  "methods": [],
  "access_semantics": [
    "All IEC HDLC setup attributes are static channel configuration parameters.",
    "comm_speed enumerates 300 through 115200 baud values and may be overridden by entering HDLC mode through another protocol.",
    "window sizes and maximum information field lengths may be negotiated to smaller values during logon."
  ],
  "behavior_notes": [
    "IEC HDLC setup configures one communication channel according to IEC 62056-46.",
    "inter_octet_time_out defines when received octets are treated as a complete frame.",
    "inactivity_time_out defines disconnection processing when no frame is received; zero disables the timeout.",
    "device_address contains the physical HDLC device address with reserved, calling, and broadcast ranges."
  ],
  "common_instances": [
    {
      "name": "IEC HDLC setup",
      "obis": "0-0:22.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.7.2 IEC HDLC setup (class_id = 23, version = 1)"
    },
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "5.7.2 IEC HDLC setup (class_id = 23, version = 0)"
    }
  ]
}
```

## Notes

