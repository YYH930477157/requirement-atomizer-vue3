---
id: KB-L2-PROFILE-BILLING
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: data_profile
layer: measurement_model
name: Billing Profile
aliases:
- periods of billing
- billing objects
keywords:
- billing profile
- periods of billing
- profile billing
- energy for billing
- tariff period
domain_tags:
- billing_profile
- measurement_data
- tariff_calendar
---

# Billing Profile

## Definition

Profile and object group for storing energy and demand quantities used for billing periods.

## Aliases

- periods of billing
- billing objects

## Domain Tags

- `billing_profile`
- `measurement_data`
- `tariff_calendar`

## Structured Data

```json metadata
{
  "typical_quantities": [
    "incremental active energy",
    "absolute active energy",
    "absolute reactive energy",
    "maximum demand",
    "UFER",
    "DMCR"
  ]
}
```

## Notes

