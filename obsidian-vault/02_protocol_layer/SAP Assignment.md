---
id: KB-L2-OBJECT-SAP-ASSIGNMENT
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: cosem_object
layer: object_model
name: SAP Assignment
aliases:
- SAP assignment object
keywords:
- sap assignment
- sap_assignment_list
- 0-0:41.0.0.255
- 0000290000ff
domain_tags:
- cosem_object
- association
- logical_device
---

# SAP Assignment

## Definition

COSEM object listing logical devices and their SAP assignments.

## Aliases

- SAP assignment object

## Domain Tags

- `cosem_object`
- `association`
- `logical_device`

## Structured Data

```json metadata
{
  "class_id": "17",
  "obis": "0-0:41.0.0.255",
  "logical_name_hex": "0000290000FF",
  "key_attributes": [
    {
      "name": "logical_name",
      "type": "octet-string[6]"
    },
    {
      "name": "SAP_assignment_list",
      "type": "asslist_type",
      "meaning": "List of logical devices"
    }
  ]
}
```

## Notes

