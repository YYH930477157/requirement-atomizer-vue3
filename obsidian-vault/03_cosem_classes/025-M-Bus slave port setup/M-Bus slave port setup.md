---
id: KB-L3-IC-25-M-BUS-SLAVE-PORT-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: M-Bus slave port setup
aliases:
- class 25
- CL 25
- M-Bus slave port
- M-Bus slave port setup object
keywords:
- m-bus slave port setup
- class 25
- cl 25
- default_baud
- available_baud
- address_state
domain_tags:
- cosem_class
- communication_profile
- m_bus
- port_setup
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# M-Bus slave port setup

## Definition

COSEM interface class for configuring the M-Bus slave port of a DLMS/COSEM device, including baud-rate capabilities and slave address state.

## Aliases

- class 25
- CL 25
- M-Bus slave port
- M-Bus slave port setup object

## Domain Tags

- `cosem_class`
- `communication_profile`
- `m_bus`
- `port_setup`

## Structured Data

```json metadata
{
  "class_id": 25,
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
      "name": "default_baud",
      "type": "enum",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Default communication speed used by the M-Bus slave port"
    },
    {
      "attribute_id": 3,
      "name": "available_baud",
      "type": "array",
      "access": "R",
      "mandatory": true,
      "meaning": "Baud rates supported by the physical M-Bus slave port"
    },
    {
      "attribute_id": 4,
      "name": "address_state",
      "type": "enum",
      "access": "R",
      "mandatory": true,
      "meaning": "State of the M-Bus slave addressing procedure"
    },
    {
      "attribute_id": 5,
      "name": "bus_address",
      "type": "long-unsigned",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Configured M-Bus slave address"
    }
  ],
  "methods": [],
  "access_semantics": [
    "The setup object configures local M-Bus slave communication parameters rather than metrology values.",
    "default_baud and bus_address are implementation configuration points and should be protected by the management access profile.",
    "available_baud and address_state are read-only diagnostic or capability attributes."
  ],
  "behavior_notes": [
    "Use this class when requirements mention M-Bus slave port speed, supported baud rates, bus address assignment, or slave address state.",
    "It complements M-Bus client/master setup classes; this object represents the local slave-side port setup."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.6 M-Bus slave port setup (class_id = 25, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with M-Bus slave port baud-rate and address-state semantics for communication setup requirements."
}
```

## Notes

- Use this class for requirements involving the meter acting as an M-Bus slave device on a local bus.
