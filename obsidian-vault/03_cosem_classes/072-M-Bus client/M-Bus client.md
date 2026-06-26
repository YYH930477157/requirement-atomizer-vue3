---
id: KB-L3-IC-72-M-BUS-CLIENT
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: M-Bus client
aliases:
- class 72
- CL 72
- wired m-bus client
- m-bus slave client
keywords:
- m-bus client
- class 72
- cl 72
- capture_period
- primary_address
- identification_number
- manufacturer_id
- m-bus value
domain_tags:
- cosem_class
- communication_profile
- m_bus
- submetering
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# M-Bus client

## Definition

COSEM interface class for representing and managing data collected from an M-Bus device through a DLMS/COSEM server.

## Aliases

- class 72
- CL 72
- wired m-bus client
- m-bus slave client

## Domain Tags

- `cosem_class`
- `communication_profile`
- `m_bus`
- `submetering`

## Structured Data

```json metadata
{
  "class_id": 72,
  "version": 2,
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
      "name": "m_bus_port_reference",
      "type": "octet-string[6]",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Reference to the M-Bus port setup object used for this client"
    },
    {
      "attribute_id": 3,
      "name": "capture_period",
      "type": "long-unsigned",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Periodic capture interval for values read from the attached M-Bus device"
    },
    {
      "attribute_id": 4,
      "name": "primary_address",
      "type": "unsigned",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Primary M-Bus address of the attached slave device"
    },
    {
      "attribute_id": 5,
      "name": "identification_number",
      "type": "double-long-unsigned",
      "access": "R",
      "mandatory": true,
      "meaning": "Identification number reported by the M-Bus device"
    },
    {
      "attribute_id": 6,
      "name": "manufacturer_id",
      "type": "long-unsigned",
      "access": "R",
      "mandatory": true,
      "meaning": "Manufacturer identifier of the attached M-Bus device"
    },
    {
      "attribute_id": 7,
      "name": "data_header",
      "type": "structure",
      "access": "R",
      "mandatory": false,
      "meaning": "Header metadata for the captured M-Bus data set"
    },
    {
      "attribute_id": 8,
      "name": "value_information",
      "type": "array",
      "access": "R",
      "mandatory": false,
      "meaning": "Value information blocks describing captured M-Bus values"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "slave_install",
      "mandatory": false,
      "meaning": "Install or bind an M-Bus slave device to the client object"
    },
    {
      "method_id": 2,
      "name": "slave_deinstall",
      "mandatory": false,
      "meaning": "Remove the binding between the client object and an M-Bus slave device"
    },
    {
      "method_id": 3,
      "name": "capture",
      "mandatory": false,
      "meaning": "Trigger capture of data from the attached M-Bus device"
    }
  ],
  "access_semantics": [
    "m_bus_port_reference and primary_address determine the physical slave selected by the client object and require controlled write access.",
    "capture_period controls polling frequency and can affect bus load and battery-powered slave behavior.",
    "Install, deinstall, and capture methods are active operations and should be reviewed as operational commands."
  ],
  "behavior_notes": [
    "Use this class when requirements mention M-Bus client, attached M-Bus slave, primary address, capture period, manufacturer ID, or imported submeter data.",
    "M-Bus client requirements often combine communication setup constraints with measurement capture and data mapping constraints."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.35 M-Bus client (class_id = 72, version = 2)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with M-Bus slave binding, capture, addressing, identification, and operational method semantics."
}
```

## Notes

- Keep M-Bus client requirements linked to both the M-Bus port setup object and the captured measurement objects.
