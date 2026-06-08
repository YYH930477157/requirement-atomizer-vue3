---
id: KB-L2-EVENT-GROUP-MODEL
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: event_model
layer: event_alarm_model
name: Event Group and Subgroup Model
aliases:
- event group/subgroup
- event numbering
keywords:
- group/subgroup of events
- event subgroup
- number of event
- description of the event
- minimum records
domain_tags:
- event
- log
- data_model
---

# Event Group and Subgroup Model

## Definition

Event model that classifies logs by group number, subgroup number, event number, and event description.

## Aliases

- event group/subgroup
- event numbering

## Domain Tags

- `event`
- `log`
- `data_model`

## Structured Data

```json metadata
{
  "fields": [
    "Group number",
    "Subgroup number",
    "Event subgroup description",
    "Number of event",
    "Description of the event",
    "Minimum records"
  ]
}
```

## Notes

