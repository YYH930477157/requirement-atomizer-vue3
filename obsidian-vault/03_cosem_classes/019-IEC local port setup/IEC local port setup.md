---
id: KB-L3-IC-19-IEC-LOCAL-PORT-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: IEC local port setup
aliases:
- class 19
- CL 19
keywords:
- iec local port setup
- optical port
- local port baud rate
- default mode
- proposed baudrate
- class 19
- cl 19
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IEC local port setup

## Definition

COSEM interface class for configuring IEC local port setup parameters in DLMS/COSEM devices.

## Aliases

- class 19
- CL 19

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 19,
  "version": 1,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "meaning": "OBIS logical name of the local port setup object"
    },
    {
      "attribute_id": 2,
      "name": "default_mode",
      "type": "enum",
      "mandatory": true,
      "meaning": "Initial IEC local port protocol mode after opening the optical/local port"
    },
    {
      "attribute_id": 3,
      "name": "default_baud",
      "type": "enum",
      "mandatory": true,
      "meaning": "Initial communication speed used before protocol negotiation"
    },
    {
      "attribute_id": 4,
      "name": "proposed_baud",
      "type": "enum",
      "mandatory": true,
      "meaning": "Baud rate proposed for the negotiated communication session"
    },
    {
      "attribute_id": 5,
      "name": "response_time",
      "type": "enum",
      "mandatory": true,
      "meaning": "IEC local-port response timing profile"
    },
    {
      "attribute_id": 6,
      "name": "device_addr",
      "type": "octet-string",
      "mandatory": true,
      "meaning": "Device address used by the IEC local port protocol"
    },
    {
      "attribute_id": 7,
      "name": "password1",
      "type": "octet-string",
      "mandatory": false,
      "meaning": "Local-port password used by lower-level IEC access where applicable"
    },
    {
      "attribute_id": 8,
      "name": "password2",
      "type": "octet-string",
      "mandatory": false,
      "meaning": "Second local-port password used by IEC access where applicable"
    },
    {
      "attribute_id": 9,
      "name": "password5",
      "type": "octet-string",
      "mandatory": false,
      "meaning": "Higher-level local-port password used by IEC access where applicable"
    }
  ],
  "methods": [],
  "access_semantics": [
    "The setup object controls local optical/IEC port negotiation and timing parameters.",
    "Password attributes are security-sensitive and should not be logged or exported in plaintext by consuming tools.",
    "Changing baud-rate or mode attributes can affect subsequent local communication sessions and should be treated as configuration writes."
  ],
  "common_instances": [
    {
      "name": "IEC local port setup",
      "obis_pattern": "0-0:20.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.19 IEC local port setup (class_id = 19, version = 1)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with local-port negotiation, baud-rate, timing, device address, and password semantics for engineering requirement composition."
}
```

## Notes

- Use this class when a requirement mentions local optical-port setup, IEC local port baud rates, IEC response time, or local-port passwords.
- Treat password attributes as credential material even when source documents list them alongside ordinary communication parameters.
