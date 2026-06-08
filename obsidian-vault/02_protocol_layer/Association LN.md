---
id: KB-L2-OBJECT-ASSOCIATION-LN
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: cosem_object
layer: object_model
name: Association LN
aliases:
- LN association object
keywords:
- association ln
- object_list
- associated_partners_id
- application_context_name
- 0-0:40.0.0.255
- 0000280000ff
domain_tags:
- cosem_object
- association
- access_control
---

# Association LN

## Definition

COSEM object representing the current logical-name association, including object list, partners, context, authentication, and security setup references.

## Aliases

- LN association object

## Domain Tags

- `cosem_object`
- `association`
- `access_control`

## Structured Data

```json metadata
{
  "class_id": "15",
  "obis": "0-0:40.0.0.255",
  "logical_name_hex": "0000280000FF",
  "key_attributes": [
    {
      "name": "logical_name",
      "type": "octet-string[6]"
    },
    {
      "name": "object_list",
      "type": "object_list_type",
      "meaning": "List of all objects"
    },
    {
      "name": "associated_partners_id",
      "type": "associated_partners_type"
    },
    {
      "name": "application_context_name",
      "type": "application_context_name"
    }
  ]
}
```

## Notes

