---
id: KB-L3-IC-24-IEC-TWISTED-PAIR-1-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: IEC twisted pair (1) setup
aliases:
- class 24
- CL 24
keywords:
- iec twisted pair (1) setup
- twisted pair setup
- IEC 62056-21 twisted pair
- local wired port
- network address
- class 24
- cl 24
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IEC twisted pair (1) setup

## Definition

COSEM interface class for configuring IEC twisted pair (1) setup parameters in DLMS/COSEM devices.

## Aliases

- class 24
- CL 24

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 24,
  "version": 1,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "meaning": "OBIS logical name of the IEC twisted-pair setup object"
    },
    {
      "attribute_id": 2,
      "name": "mode",
      "type": "enum",
      "mandatory": true,
      "meaning": "Operating mode of the IEC twisted-pair communication port"
    },
    {
      "attribute_id": 3,
      "name": "speed",
      "type": "enum",
      "mandatory": true,
      "meaning": "Configured communication speed for the twisted-pair link"
    },
    {
      "attribute_id": 4,
      "name": "primary_address",
      "type": "unsigned",
      "mandatory": true,
      "meaning": "Primary address used on the IEC twisted-pair bus"
    },
    {
      "attribute_id": 5,
      "name": "tabis",
      "type": "long-unsigned",
      "mandatory": false,
      "meaning": "Timing parameter used by IEC twisted-pair communication"
    }
  ],
  "methods": [],
  "access_semantics": [
    "The setup object defines wired IEC twisted-pair communication parameters, including mode, speed, and bus addressing.",
    "Address and speed writes affect physical-link interoperability and should be validated against the meter profile before applying.",
    "Timing parameters should be treated as protocol configuration rather than metering data."
  ],
  "common_instances": [
    {
      "name": "IEC twisted pair setup",
      "obis_pattern": "0-0:23.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.24 IEC twisted pair (1) setup (class_id = 24, version = 1)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with wired IEC mode, speed, address, and timing semantics."
}
```

## Notes

- Use this class when requirements mention local wired IEC communication, twisted-pair baud rate/speed, or primary bus address configuration.
