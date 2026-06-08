---
id: KB-L2-OBJECT-COSEM-LOGICAL-DEVICE-NAME
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: cosem_object
layer: object_model
name: COSEM Logical Device Name
aliases:
- logical device name object
keywords:
- cosem logical device name
- 0-0:42.0.0.255
- 00002a0000ff
- unique logical device identification
domain_tags:
- cosem_object
- logical_device
- device_identifier
---

# COSEM Logical Device Name

## Definition

COSEM data object containing the unique logical device identification.

## Aliases

- logical device name object

## Domain Tags

- `cosem_object`
- `logical_device`
- `device_identifier`

## Structured Data

```json metadata
{
  "class_id": "1",
  "obis": "0-0:42.0.0.255",
  "logical_name_hex": "00002A0000FF",
  "key_attributes": [
    {
      "name": "logical_name",
      "type": "octet-string[6]"
    },
    {
      "name": "value",
      "type": "octet-string[16]",
      "meaning": "Unique logical device identification"
    }
  ]
}
```

## Notes

