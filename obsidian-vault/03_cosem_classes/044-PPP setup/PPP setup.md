---
id: KB-L3-IC-44-PPP-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PPP setup
aliases:
- class 44
- CL 44
- PPP configuration
- PPP setup object
keywords:
- ppp setup
- class 44
- cl 44
- phy_reference
- lcp_options
- ipcp_options
- ppp authentication
domain_tags:
- cosem_class
- communication_profile
- ppp
- network_setup
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PPP setup

## Definition

COSEM interface class for configuring Point-to-Point Protocol setup parameters, including physical link reference and negotiated PPP options.

## Aliases

- class 44
- CL 44
- PPP configuration
- PPP setup object

## Domain Tags

- `cosem_class`
- `communication_profile`
- `ppp`
- `network_setup`

## Structured Data

```json metadata
{
  "class_id": 44,
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
      "name": "PHY_reference",
      "type": "octet-string[6]",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Logical name reference to the physical communication setup object used below PPP"
    },
    {
      "attribute_id": 3,
      "name": "LCP_options",
      "type": "array",
      "access": "R/W",
      "mandatory": true,
      "meaning": "PPP Link Control Protocol options supported or negotiated by the device"
    },
    {
      "attribute_id": 4,
      "name": "IPCP_options",
      "type": "array",
      "access": "R/W",
      "mandatory": true,
      "meaning": "PPP IP Control Protocol options for IP layer negotiation"
    },
    {
      "attribute_id": 5,
      "name": "PPP_authentication",
      "type": "structure",
      "access": "R/W",
      "mandatory": false,
      "meaning": "Authentication parameters used by PPP when required by the profile"
    }
  ],
  "methods": [],
  "access_semantics": [
    "PHY_reference links PPP setup to the underlying serial, modem, or other physical communication setup object.",
    "LCP_options and IPCP_options determine negotiated link and IP behavior and should be managed by authorized clients.",
    "PPP authentication values are security-sensitive and should not be exposed to low-privilege clients."
  ],
  "behavior_notes": [
    "Use this class when requirements mention PPP negotiation, LCP, IPCP, physical-link reference, or PPP authentication.",
    "PPP setup is part of the communication stack and should be linked to TCP-UDP/IP setup requirements when IP transport is used."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.7.22 PPP setup (class_id = 44, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with PPP link-reference, LCP/IPCP, and authentication semantics."
}
```

## Notes

- Use this class for requirements that describe PPP as the transport adaptation layer before IP communication.
