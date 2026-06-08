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
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "communication_speed",
      "type": "enum",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "window_size_transmit",
      "type": "long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "window_size_receive",
      "type": "long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "maximum_info_field_length_transmit",
      "type": "long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "maximum_info_field_length_receive",
      "type": "long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 7,
      "name": "inter_octet_time_out",
      "type": "long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 8,
      "name": "inactivity_time_out",
      "type": "long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 9,
      "name": "device_address",
      "type": "long-unsigned",
      "mandatory": true
    }
  ],
  "methods": []
}
```

## Notes

