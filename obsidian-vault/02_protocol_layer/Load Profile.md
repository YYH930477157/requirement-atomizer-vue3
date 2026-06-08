---
id: KB-L2-PROFILE-LOAD
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: data_profile
layer: measurement_model
name: Load Profile
aliases:
- load curve
- load profile quality
keywords:
- load profile
- load curve
- load profile quality
- incremental load curve
- absolute load curve
domain_tags:
- load_profile
- measurement_data
---

# Load Profile

## Definition

Time-series profile for load curve records and related measurement quantities.

## Aliases

- load curve
- load profile quality

## Domain Tags

- `load_profile`
- `measurement_data`

## Structured Data

```json metadata
{
  "typical_quantities": [
    "incremental active energy",
    "absolute active energy",
    "incremental reactive energy",
    "absolute reactive energy"
  ]
}
```

## Notes

