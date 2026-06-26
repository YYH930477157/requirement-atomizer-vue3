---
id: KB-L3-IC-74-M-BUS-MASTER-PORT-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: M-Bus master port setup
aliases:
- class 74
- CL 74
- m-bus master port
- wired m-bus port setup
keywords:
- m-bus master port setup
- class 74
- cl 74
- m-bus baud rate
- m-bus address
- m-bus communication speed
- m-bus port reference
domain_tags:
- cosem_class
- communication_profile
- m_bus
- port_setup
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# M-Bus master port setup

## Definition

COSEM interface class for configuring M-Bus master port setup parameters in DLMS/COSEM devices.

## Aliases

- class 74
- CL 74
- m-bus master port
- wired m-bus port setup

## Domain Tags

- `cosem_class`
- `communication_profile`
- `m_bus`
- `port_setup`

## Structured Data

```json metadata
{
  "class_id": 74,
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
      "name": "comm_speed",
      "type": "enum",
      "access": "R/W",
      "mandatory": true,
      "meaning": "M-Bus communication speed used by the master port"
    },
    {
      "attribute_id": 3,
      "name": "m_bus_profile",
      "type": "enum",
      "access": "R/W",
      "mandatory": false,
      "meaning": "M-Bus profile or mode used on the port when the implementation supports multiple profiles"
    },
    {
      "attribute_id": 4,
      "name": "active_devices",
      "type": "array",
      "access": "R",
      "mandatory": false,
      "meaning": "List or count of active M-Bus devices known on the master port"
    }
  ],
  "methods": [],
  "access_semantics": [
    "comm_speed must match the attached M-Bus segment and should be writable only through authorized communication configuration.",
    "active_devices is diagnostic/inventory information and should be interpreted together with M-Bus client objects.",
    "Changing port setup can temporarily disrupt reads from all clients using the same M-Bus master port."
  ],
  "behavior_notes": [
    "Use this class when requirements mention M-Bus master port speed, bus profile, active devices, or wired M-Bus segment setup.",
    "This class configures the shared bus port; per-slave capture behavior belongs to M-Bus client objects."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.37 M-Bus master port setup (class_id = 74, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with M-Bus port speed, profile, inventory, and shared-port behavior semantics."
}
```

## Notes

- Treat this as shared communication setup for all M-Bus clients bound to the port.
