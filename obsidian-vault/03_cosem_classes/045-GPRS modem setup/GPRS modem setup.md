---
id: KB-L3-IC-45-GPRS-MODEM-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: GPRS modem setup
aliases:
- class 45
- CL 45
- GPRS modem configuration
- cellular modem setup
keywords:
- gprs modem setup
- class 45
- cl 45
- apn
- pin code
- quality_of_service
- cellular modem
- gprs qos
domain_tags:
- cosem_class
- communication_profile
- cellular
- network_setup
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# GPRS modem setup

## Definition

COSEM interface class for configuring GPRS modem setup parameters in DLMS/COSEM devices.

## Aliases

- class 45
- CL 45
- GPRS modem configuration
- cellular modem setup

## Domain Tags

- `cosem_class`
- `communication_profile`
- `cellular`
- `network_setup`

## Structured Data

```json metadata
{
  "class_id": 45,
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
      "name": "APN",
      "type": "visible-string",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Access Point Name used by the cellular network connection"
    },
    {
      "attribute_id": 3,
      "name": "PIN_code",
      "type": "visible-string",
      "access": "R/W",
      "mandatory": false,
      "meaning": "SIM PIN or access credential required by the cellular modem"
    },
    {
      "attribute_id": 4,
      "name": "default_quality_of_service",
      "type": "structure",
      "access": "R/W",
      "mandatory": false,
      "meaning": "Default GPRS quality-of-service parameters requested by the device"
    },
    {
      "attribute_id": 5,
      "name": "requested_quality_of_service",
      "type": "structure",
      "access": "R/W",
      "mandatory": false,
      "meaning": "Requested GPRS quality-of-service parameters for network attachment"
    }
  ],
  "methods": [],
  "access_semantics": [
    "APN controls cellular packet data attachment and should be configurable only by authorized clients.",
    "PIN_code is credential-like data and should not be exposed in low-privilege read contexts.",
    "Quality-of-service attributes affect cellular network behavior and should be validated against the supported profile."
  ],
  "behavior_notes": [
    "Use this class when requirements mention GPRS, cellular modem APN, SIM PIN, or GPRS quality of service.",
    "GPRS modem setup is normally paired with IP, TCP-UDP, PPP, or application-layer setup requirements."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.23 GPRS modem setup (class_id = 45, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with cellular APN, PIN, quality-of-service, and credential handling semantics."
}
```

## Notes

- Treat APN and PIN handling as configuration requirements, not as measurement data.
