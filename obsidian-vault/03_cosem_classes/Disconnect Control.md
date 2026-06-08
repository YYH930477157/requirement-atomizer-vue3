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
      "name": "remote_reconnect"
    }
  ]
}
```

## Notes

