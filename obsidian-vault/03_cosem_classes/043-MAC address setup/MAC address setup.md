---
id: KB-L3-IC-43-MAC-ADDRESS-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: MAC address setup
aliases:
- class 43
- CL 43
- MAC address object
- Ethernet MAC address setup
keywords:
- mac address setup
- class 43
- cl 43
- mac_address
- ethernet address
- physical address
domain_tags:
- cosem_class
- communication_profile
- network_setup
- ethernet
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# MAC address setup

## Definition

COSEM interface class for exposing or configuring the network MAC address used by DLMS/COSEM communication profiles.

## Aliases

- class 43
- CL 43
- MAC address object
- Ethernet MAC address setup

## Domain Tags

- `cosem_class`
- `communication_profile`
- `network_setup`
- `ethernet`

## Structured Data

```json metadata
{
  "class_id": 43,
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
      "name": "MAC_address",
      "type": "octet-string",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Layer-2 MAC address assigned to the communication interface"
    }
  ],
  "methods": [],
  "access_semantics": [
    "MAC_address identifies the local layer-2 network interface and is usually read by clients for communication inventory.",
    "Write access to MAC_address, when supported by a profile, should be limited to management clients because it changes network identity."
  ],
  "behavior_notes": [
    "Use this class when requirements mention MAC address setup, Ethernet physical address, or layer-2 interface identity.",
    "It is normally used together with TCP-UDP, IPv4, IPv6, PPP, or other communication setup classes."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.21 MAC address setup (class_id = 43, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with MAC_address attribute and layer-2 identity semantics."
}
```

## Notes

- Use this class to anchor requirements about communication-interface hardware identity.
