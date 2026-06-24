---
id: KB-L3-IC-70-DISCONNECT-CONTROL
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Disconnect Control
aliases:
- class 70
- CL 70
keywords:
- class 70
- cl 70
- disconnect control
- output_state
- control_state
- control_mode
- remote_disconnect
- remote_reconnect
- Ready_for_reconnection
- control_mode
domain_tags:
- cosem_class
- disconnect_control
- meter_function
---

# Disconnect Control

## Definition

COSEM interface class for disconnect/reconnect control.

## Aliases

- class 70
- CL 70

## Domain Tags

- `cosem_class`
- `disconnect_control`
- `meter_function`

## Structured Data

```json metadata
{
  "class_id": 70,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "output_state",
      "type": "boolean",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "control_state",
      "type": "enum",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "control_mode",
      "type": "enum",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "remote_disconnect"
    },
    {
      "method_id": 2,
      "name": "remote_reconnect",
      "parameter_type": "integer(0)"
    }
  ],
  "state_model": {
    "states": [
      {"value": 0, "name": "Disconnected", "output_state": false},
      {"value": 1, "name": "Connected", "output_state": true},
      {"value": 2, "name": "Ready_for_reconnection", "output_state": false}
    ],
    "triggers": ["remote_disconnect", "remote_reconnect", "manual_disconnect", "manual_reconnect", "local_disconnect", "local_reconnect"],
    "control_mode_note": "control_mode configures which remote, manual, and local transitions are allowed."
  },
  "behavior_notes": [
    "remote_disconnect forces the object into Disconnected when remote disconnection is enabled.",
    "remote_reconnect either reconnects directly or moves to Ready_for_reconnection depending on control_mode.",
    "The object has no command memory; commands are executed immediately."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.5.8 Disconnect control (class_id = 70, version = 1)"
    }
  ]
}
```

## Notes

