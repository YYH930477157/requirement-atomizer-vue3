---
id: KB-L2-OBJECT-DEVICE-ID-1
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: cosem_object
layer: object_model
name: Device ID 1
aliases:
- meter serial number object
keywords:
- device id 1
- 0-0:96.1.0.255
- 0000600100ff
- electronic meter serial number
domain_tags:
- cosem_object
- device_identifier
- meter_function
---

# Device ID 1

## Definition

COSEM data object containing the electronic meter serial number.

## Aliases

- meter serial number object

## Domain Tags

- `cosem_object`
- `device_identifier`
- `meter_function`

## Structured Data

```json metadata
{
  "class_id": "1",
  "obis": "0-0:96.1.0.255",
  "logical_name_hex": "0000600100FF",
  "key_attributes": [
    {
      "name": "logical_name",
      "type": "octet-string[6]"
    },
    {
      "name": "value",
      "type": "octet-string[10]",
      "meaning": "Electronic meter serial number"
    }
  ]
}
```

## Notes

