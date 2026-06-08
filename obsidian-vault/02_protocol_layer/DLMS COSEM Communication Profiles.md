---
id: KB-L2-COMMUNICATION-PROFILES
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: communication_profile_set
layer: communication_model
name: DLMS/COSEM Communication Profiles
aliases:
- communication profiles
- communication profile set
keywords:
- communication profiles
- hdlc
- plc-prime
- rf-wi-sun
- rf-lorawan
- pull
- push
domain_tags:
- communication_profile
- dlms_cosem
---

# DLMS/COSEM Communication Profiles

## Definition

Communication profiles considered for the DLMS/COSEM smart meter profile.

## Aliases

- communication profiles
- communication profile set

## Domain Tags

- `communication_profile`
- `dlms_cosem`

## Structured Data

```json metadata
{
  "profiles": [
    {
      "name": "HDLC",
      "medium": "data link / serial or IP-related DLMS profile context"
    },
    {
      "name": "PLC-PRIME",
      "medium": "power line communication"
    },
    {
      "name": "RF-Wi-SUN",
      "medium": "radio frequency mesh"
    },
    {
      "name": "RF-LoRaWAN",
      "medium": "low-power wide-area radio"
    }
  ],
  "required_mechanisms": [
    "pull",
    "push"
  ]
}
```

## Notes

