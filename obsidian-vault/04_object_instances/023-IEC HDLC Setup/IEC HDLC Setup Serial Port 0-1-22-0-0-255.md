---
id: KB-OBIS-0-1-22-0-0-255-IEC-HDLC-SETUP-SERIAL-PORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: IEC HDLC setup - Serial port
aliases:
- IEC HDLC setup serial port 0-1:22.0.0.255
- Serial port HDLC setup
keywords:
- 0-1:22.0.0.255
- IEC HDLC setup - Serial port
- serial port HDLC setup
- serial IEC HDLC setup
domain_tags:
- cosem_object
- communication_profile
- hdlc
- serial_port
relations:
- relation: instance_of
  target: KB-L3-IC-23-IEC-HDLC-SETUP
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# IEC HDLC setup - Serial port

## Definition

Row-level IEC HDLC setup object for the serial communication port at logical name `0-1:22.0.0.255`.

## Aliases

- IEC HDLC setup serial port 0-1:22.0.0.255
- Serial port HDLC setup

## Domain Tags

- `cosem_object`
- `communication_profile`
- `hdlc`
- `serial_port`

## Relations

- `instance_of` -> `KB-L3-IC-23-IEC-HDLC-SETUP`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-1:22.0.0.255",
  "likely_interface_class_id": 23,
  "likely_interface_class_name": "IEC HDLC Setup",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 serial communication channel",
    "C": "22 IEC HDLC setup",
    "D": "0 default setup instance",
    "E": "0 default HDLC setup object",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    },
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "IEC HDLC setup interface class"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "IEC HDLC setup - Serial port at 0-1:22.0.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching serial-port HDLC address, window, frame-size, or inter-octet timing requirements.",
    "The B value distinguishes the serial port instance from other IEC HDLC setup channels."
  ]
}
```

## Notes
