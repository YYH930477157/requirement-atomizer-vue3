---
id: KB-L2-OBJECT-IMAGE-TRANSFER
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: cosem_object
layer: object_model
name: Image Transfer
aliases:
- firmware image transfer object
keywords:
- image transfer
- image_block_size
- image_transfer_enabled
- image_transfer_status
- image_to_activate_info
- 0-0:44.0.0.255
- 00002c0000ff
domain_tags:
- cosem_object
- firmware_update
- meter_function
---

# Image Transfer

## Definition

COSEM object allowing firmware image transfer to COSEM servers.

## Aliases

- firmware image transfer object

## Domain Tags

- `cosem_object`
- `firmware_update`
- `meter_function`

## Structured Data

```json metadata
{
  "class_id": "18",
  "obis": "0-0:44.0.0.255",
  "logical_name_hex": "00002C0000FF",
  "key_attributes": [
    {
      "name": "logical_name",
      "type": "octet-string[6]"
    },
    {
      "name": "image_block_size",
      "type": "double-long-unsigned"
    },
    {
      "name": "image_transferred_blocks_status",
      "type": "bit-string"
    },
    {
      "name": "image_first_not_transferred_block_number",
      "type": "double-long-unsigned"
    },
    {
      "name": "image_transfer_enabled",
      "type": "boolean"
    },
    {
      "name": "image_transfer_status",
      "type": "enumerated"
    },
    {
      "name": "image_to_activate_info",
      "type": "array"
    }
  ]
}
```

## Notes

