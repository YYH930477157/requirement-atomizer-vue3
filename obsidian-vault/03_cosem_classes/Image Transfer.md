---
id: KB-L3-IC-18-IMAGE-TRANSFER
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Image Transfer
aliases:
- Firmware Image Transfer
- class 18
- CL 18
keywords:
- class 18
- cl 18
- image transfer
- image_block_size
- image_transferred_blocks_status
- image_transfer_enabled
- image_transfer_status
- image_to_activate_info
- image_activate
- image_verify
domain_tags:
- cosem_class
- firmware_update
- meter_function
---

# Image Transfer

## Definition

COSEM interface class for transferring and activating firmware images.

## Aliases

- Firmware Image Transfer
- class 18
- CL 18

## Domain Tags

- `cosem_class`
- `firmware_update`
- `meter_function`

## Structured Data

```json metadata
{
  "class_id": 18,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "image_block_size",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "image_transferred_blocks_status",
      "type": "bit-string",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "image_first_not_transferred_block_number",
      "type": "double-long-unsigned",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "image_transfer_enabled",
      "type": "boolean",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "image_transfer_status",
      "type": "enumerated",
      "mandatory": true
    },
    {
      "attribute_id": 7,
      "name": "image_to_activate_info",
      "type": "array",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "image_transfer_initiate"
    },
    {
      "method_id": 2,
      "name": "image_block_transfer"
    },
    {
      "method_id": 3,
      "name": "image_verify"
    },
    {
      "method_id": 4,
      "name": "image_activate"
    }
  ],
  "common_instances": [
    {
      "name": "Image Transfer",
      "obis": "0-0:44.0.0.255"
    }
  ],
  "behavior_notes": [
    "Image transfer is initiated, transferred block by block, verified, and then activated.",
    "image_transferred_blocks_status tracks which blocks have already been transferred.",
    "image_transfer_enabled controls whether the image transfer procedure is permitted."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.6 Image transfer (class_id = 18, version = 0)"
    }
  ]
}
```

## Notes

