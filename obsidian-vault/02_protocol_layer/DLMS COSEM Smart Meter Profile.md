---
id: KB-L2-DLMS-COSEM-PROFILE
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: protocol_profile
layer: protocol_architecture
name: DLMS/COSEM Smart Meter Profile
aliases:
- DLMS/COSEM profile
- DLMS profile
- Smart meter profile
keywords:
- dlms/cosem profile
- dlms profile
- smart meter profile
- profile dlms/cosem
domain_tags:
- dlms_cosem
- protocol_profile
- smart_meter
relations:
- relation: uses
  target: KB-L2-XDLMS-SERVICES
- relation: uses
  target: KB-L2-COSEM-OBJECT-MODEL
- relation: uses
  target: KB-L2-OBIS-LOGICAL-NAME
- relation: secured_by
  target: KB-L2-SECURITY-SUITES
- relation: transported_by
  target: KB-L2-COMMUNICATION-PROFILES
---

# DLMS/COSEM Smart Meter Profile

## Definition

Application and object profile for smart electricity meters using DLMS/COSEM services and COSEM objects.

## Aliases

- DLMS/COSEM profile
- DLMS profile
- Smart meter profile

## Domain Tags

- `dlms_cosem`
- `protocol_profile`
- `smart_meter`

## Relations

- `uses` -> `KB-L2-XDLMS-SERVICES`
- `uses` -> `KB-L2-COSEM-OBJECT-MODEL`
- `uses` -> `KB-L2-OBIS-LOGICAL-NAME`
- `secured_by` -> `KB-L2-SECURITY-SUITES`
- `transported_by` -> `KB-L2-COMMUNICATION-PROFILES`

## Structured Data

```json metadata
{
  "components": [
    "DLMS/COSEM application layer",
    "xDLMS services",
    "COSEM interface classes",
    "OBIS logical names",
    "client/server associations",
    "security suites",
    "communication profiles"
  ]
}
```

## Notes

