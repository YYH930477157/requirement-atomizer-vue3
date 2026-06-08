---
id: KB-L2-OBJECT-DISCONNECT-CONTROL-SCHEDULER
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: cosem_object
layer: object_model
name: Disconnect Control Scheduler
aliases:
- disconnection scheduler
keywords:
- disconnect control scheduler
- executed_script
- execution_time
- 0-0:15.0.1.255
- disconnect
- reconnect
domain_tags:
- cosem_object
- disconnect_control
- meter_function
---

# Disconnect Control Scheduler

## Definition

COSEM schedule object used to trigger disconnect and reconnect scripts.

## Aliases

- disconnection scheduler

## Domain Tags

- `cosem_object`
- `disconnect_control`
- `meter_function`

## Structured Data

```json metadata
{
  "class_id": "22",
  "obis": "0-0:15.0.1.255",
  "key_attributes": [
    {
      "name": "logical_name",
      "type": "octet-string[6]"
    },
    {
      "name": "executed_script",
      "type": "Script",
      "meaning": "script identifier for disconnect or reconnect"
    },
    {
      "name": "execution_time",
      "type": "array",
      "meaning": "Date and time"
    }
  ]
}
```

## Notes

