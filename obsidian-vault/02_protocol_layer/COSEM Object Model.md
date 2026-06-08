---
id: KB-L2-COSEM-OBJECT-MODEL
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: object_model
layer: object_model
name: COSEM Object Model
aliases:
- COSEM interface class model
- COSEM objects
keywords:
- cosem object
- interface class
- class_id
- attribute
- method
- object/attribute name
- cl
domain_tags:
- cosem_object
- data_model
---

# COSEM Object Model

## Definition

COSEM objects are instances of interface classes identified by logical names and defined by attributes, methods, access rights, and data types.

## Aliases

- COSEM interface class model
- COSEM objects

## Domain Tags

- `cosem_object`
- `data_model`

## Structured Data

```json metadata
{
  "core_fields": [
    "Object/attribute name",
    "CL",
    "logical_name",
    "Type",
    "Value",
    "Meaning",
    "Access rights RC/PC/SC/LC"
  ]
}
```

## Notes

