---
id: KB-L2-MANAGEMENT-LOGICAL-DEVICE
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: logical_device
layer: object_model
name: Management Logical Device
aliases:
- management device
- SAP 0x01 logical device
keywords:
- management logical device
- device logical in management
- sap = 0x01
domain_tags:
- logical_device
- data_model
- device_management
relations:
- relation: contains
  target: KB-L2-OBJECT-SAP-ASSIGNMENT
- relation: contains
  target: KB-L2-OBJECT-ASSOCIATION-LN
- relation: contains
  target: KB-L2-OBJECT-IMAGE-TRANSFER
---

# Management Logical Device

## Definition

Mandatory logical device in a physical meter that exposes device management information, structure discovery, configuration, events, alarms, firmware update, and security-related objects.

## Aliases

- management device
- SAP 0x01 logical device

## Domain Tags

- `logical_device`
- `data_model`
- `device_management`

## Relations

- `contains` -> `KB-L2-OBJECT-SAP-ASSIGNMENT`
- `contains` -> `KB-L2-OBJECT-ASSOCIATION-LN`
- `contains` -> `KB-L2-OBJECT-IMAGE-TRANSFER`

## Structured Data

```json metadata
{
  "sap": "0x01",
  "typical_object_groups": [
    "SAP assignment",
    "Association LN",
    "Security setup",
    "Clock",
    "Activity calendar",
    "Event log",
    "Alarm handling",
    "Firmware image transfer"
  ]
}
```

## Notes

