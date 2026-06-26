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
- ppp_authentication
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

COSEM interface class (class_id = 44, version = 0) for modelling the setup of interfaces using the PPP protocol, handling all information related to PPP settings of a given physical device and lower layer connection. One instance per network interface (cardinality 0...n).

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

## Access Semantics

All attributes are **static**, read-write (RW) via the SET service by an authorised management client. logical_name is read-only for all clients. The LCP/IPCP options and PPP authentication govern the PPP link negotiation per IETF STD 51 / RFC 1661.

## Behavior Notes

- A device has one PPP setup instance per network interface. Cardinality 0...n.
- **PHY_reference** (attr 2): references the physical layer interface object by logical_name that supports the PPP layer.
- **LCP_options** (attr 3): array of LCP configuration option structures (LCP_Option_Type, LCP_Option_Length, LCP_Option_Data). Supported types per IETF STD 51/RFC 1661: MRU (type 1, default 1500 octets), ACCM (type 2), Authentication-Protocol (type 3, default no auth), Magic-Number (type 5), Protocol-Field-Compression (type 7), FCS-Alternatives (type 9), Address-and-Control-Field-Compression (type 10), Callback (type 13).
- **IPCP_options** (attr 4): array of IPCP configuration option structures for IP parameters over PPP.
- **PPP_authentication** (attr 5): PPP authentication parameters (e.g. PAP/CHAP) per the PPP_auth_type structure.
- **No specific methods**: configuration is done entirely via SET on the static option structures.

## Structured Data

```json metadata
{
  "class_id": 44,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "PHY_reference", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x08"},
    {"attribute_id": 3, "name": "LCP_options", "type": "LCP_options_type", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "IPCP_options", "type": "IPCP_options_type", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x18"},
    {"attribute_id": 5, "name": "PPP_authentication", "type": "PPP_auth_type", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x20"}
  ],
  "methods": [],
  "enum_definitions": {
    "LCP_Option_Type": {"1": "MRU (default 1500)", "2": "ACCM (Async-Control-Character-Map)", "3": "Authentication-Protocol (default no auth)", "5": "Magic-Number", "7": "Protocol-Field-Compression", "9": "FCS-Alternatives", "10": "Address-and-Control-Field-Compression", "13": "Callback"}
  },
  "access_semantics": [
    "All attributes are static, read-write (RW) via SET by an authorised management client; logical_name read-only for all.",
    "PHY_reference points to the physical layer interface object supporting the PPP layer.",
    "LCP_options and IPCP_options govern PPP link and IP-layer negotiation per IETF STD 51 / RFC 1661.",
    "PPP_authentication carries authentication parameters (e.g. PAP/CHAP)."
  ],
  "behavior_notes": [
    "A device has one PPP setup instance per network interface. Cardinality 0...n.",
    "LCP_options: array of {Type, Length, Data} structures; MRU default 1500 octets, Authentication-Protocol default no auth.",
    "IPCP_options: array of IP-layer negotiation option structures.",
    "PPP_authentication: authentication type/parameters per PPP_auth_type."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.9.5 PPP setup (class_id = 44, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.9.5. Full attributes with access_rights, LCP option enum definitions, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.9.5 (page 295-296).
- LCP/IPCP option values per IANA PPP Protocol Field Assignments.
- Use this class for requirements that describe PPP as the transport adaptation layer before IP communication.
