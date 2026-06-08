---
id: KB-L2-XDLMS-SERVICES
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: service_set
layer: application_layer
name: xDLMS Services
aliases:
- DLMS services
- xDLMS service set
keywords:
- xdlms service
- services xdlms
- block transfer with get
- block transfer with set
- eventnotification
- datanotification
- selective access
domain_tags:
- dlms_cosem
- application_layer
- service_model
relations:
- relation: used_by
  target: KB-L2-CLIENT-PUBLIC
- relation: used_by
  target: KB-L2-CLIENT-REMOTE-MANAGEMENT
- relation: used_by
  target: KB-L2-CLIENT-LOCAL-MANAGEMENT
- relation: used_by
  target: KB-L2-CLIENT-READ
---

# xDLMS Services

## Definition

Service set used by DLMS/COSEM clients to read, write, invoke methods, receive events, and receive pushed data.

## Aliases

- DLMS services
- xDLMS service set

## Domain Tags

- `dlms_cosem`
- `application_layer`
- `service_model`

## Relations

- `used_by` -> `KB-L2-CLIENT-PUBLIC`
- `used_by` -> `KB-L2-CLIENT-REMOTE-MANAGEMENT`
- `used_by` -> `KB-L2-CLIENT-LOCAL-MANAGEMENT`
- `used_by` -> `KB-L2-CLIENT-READ`

## Structured Data

```json metadata
{
  "services": [
    {
      "name": "GET",
      "purpose": "Read COSEM object attributes"
    },
    {
      "name": "SET",
      "purpose": "Write COSEM object attributes"
    },
    {
      "name": "ACTION",
      "purpose": "Invoke COSEM object methods"
    },
    {
      "name": "ACCESS selective",
      "purpose": "Access selected data ranges or entries"
    },
    {
      "name": "EventNotification",
      "purpose": "Notify event occurrences"
    },
    {
      "name": "DataNotification",
      "purpose": "Push data notification"
    }
  ]
}
```

## Notes

