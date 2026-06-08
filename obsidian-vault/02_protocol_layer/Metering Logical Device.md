---
id: KB-L2-METERING-LOGICAL-DEVICE
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: logical_device
layer: object_model
name: Metering Logical Device
aliases:
- measurement logical device
- measuring logic device
keywords:
- metering logical device
- measurement logical device
- measuring logic device
- devices in measurement
domain_tags:
- logical_device
- measurement_data
- meter_function
relations:
- relation: contains
  target: KB-L2-PROFILE-BILLING
- relation: contains
  target: KB-L2-PROFILE-LOAD
- relation: contains
  target: KB-L2-PROFILE-POWER-QUALITY
---

# Metering Logical Device

## Definition

Logical device that exposes the meter's measurement and billing functionality through COSEM objects.

## Aliases

- measurement logical device
- measuring logic device

## Domain Tags

- `logical_device`
- `measurement_data`
- `meter_function`

## Relations

- `contains` -> `KB-L2-PROFILE-BILLING`
- `contains` -> `KB-L2-PROFILE-LOAD`
- `contains` -> `KB-L2-PROFILE-POWER-QUALITY`

## Structured Data

```json metadata
{
  "typical_object_groups": [
    "Energy registers",
    "Demand registers",
    "Billing profile",
    "Load profile",
    "Power quality objects",
    "Snapshot values"
  ]
}
```

## Notes

