---
id: KB-OBIS-0-2-22-0-0-255-IEC-HDLC-SETUP-OPTICAL-PORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: IEC HDLC setup - Optical port
aliases:
- IEC HDLC setup optical port 0-2:22.0.0.255
- Optical port HDLC setup
keywords:
- 0-2:22.0.0.255
- IEC HDLC setup - Optical port
- optical port HDLC setup
- optical IEC HDLC setup
domain_tags:
- cosem_object
- communication_profile
- hdlc
- optical_port
relations:
- relation: instance_of
  target: KB-L3-IC-23-IEC-HDLC-SETUP
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# IEC HDLC setup - Optical port

## Definition

Row-level IEC HDLC setup object for the optical communication port at logical name `0-2:22.0.0.255`.

## Aliases

- IEC HDLC setup optical port 0-2:22.0.0.255
- Optical port HDLC setup

## Domain Tags

- `cosem_object`
- `communication_profile`
- `hdlc`
- `optical_port`

## Relations

- `instance_of` -> `KB-L3-IC-23-IEC-HDLC-SETUP`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-2:22.0.0.255",
  "likely_interface_class_id": 23,
  "likely_interface_class_name": "IEC HDLC Setup",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "2 optical communication channel",
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
      "section": "IEC HDLC setup - Optical port at 0-2:22.0.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching optical-port HDLC address, frame-size, window, or timing requirements.",
    "The B value distinguishes the optical-port instance from other IEC HDLC setup channels."
  ]
}
```

## Notes
