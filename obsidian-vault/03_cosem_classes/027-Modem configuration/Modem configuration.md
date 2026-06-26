---
id: KB-L3-IC-27-MODEM-CONFIGURATION
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Modem configuration
aliases:
- class 27
- CL 27
keywords:
- modem configuration
- initialization string
- modem profile
- communication speed
- PSTN modem
- class 27
- cl 27
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Modem configuration

## Definition

COSEM interface class for configuring modem communication profiles and initialization behavior.

## Aliases

- class 27
- CL 27

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 27,
  "version": 1,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "meaning": "OBIS logical name of the modem configuration object"
    },
    {
      "attribute_id": 2,
      "name": "comm_speed",
      "type": "enum",
      "mandatory": true,
      "meaning": "Configured modem communication speed"
    },
    {
      "attribute_id": 3,
      "name": "initialization_string",
      "type": "octet-string",
      "mandatory": true,
      "meaning": "Command string used to initialize the modem before communication"
    },
    {
      "attribute_id": 4,
      "name": "modem_profile",
      "type": "array",
      "mandatory": false,
      "meaning": "Profile of modem initialization and communication settings"
    }
  ],
  "methods": [],
  "access_semantics": [
    "The object stores modem initialization and speed parameters used before establishing a communication session.",
    "Initialization strings are configuration commands and may contain vendor-specific modem control sequences.",
    "Profile changes can alter remote communication availability and should be reviewed as communication configuration."
  ],
  "common_instances": [
    {
      "name": "Modem configuration",
      "obis_pattern": "0-0:2.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.27 Modem configuration (class_id = 27, version = 1)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with modem speed, initialization string, and profile semantics."
}
```

## Notes

- Use this class when requirements mention modem initialization, dial-up communication, or communication-speed configuration.
