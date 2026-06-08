---
id: KB-L2-OBIS-LOGICAL-NAME
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: code_structure
layer: object_model
name: OBIS Logical Name
aliases:
- logical_name
- OBIS value
keywords:
- logical_name
- logical name
- obis
- '0-0:'
- '255'
domain_tags:
- obis_code
- cosem_object
- data_model
---

# OBIS Logical Name

## Definition

Logical name used to identify COSEM object instances, commonly represented as six OBIS value groups.

## Aliases

- logical_name
- OBIS value

## Domain Tags

- `obis_code`
- `cosem_object`
- `data_model`

## Structured Data

```json metadata
{
  "format": "A-B:C.D.E.F",
  "examples": [
    {
      "value": "0-0:41.0.0.255",
      "object": "SAP Assignment"
    },
    {
      "value": "0-0:40.0.0.255",
      "object": "Association LN"
    },
    {
      "value": "0-0:42.0.0.255",
      "object": "COSEM logical device name"
    },
    {
      "value": "0-0:44.0.0.255",
      "object": "Image Transfer"
    }
  ]
}
```

## Notes

