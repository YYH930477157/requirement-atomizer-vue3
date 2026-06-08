---
id: KB-L2-ACCESS-RIGHTS-MODEL
kb_id: energy_metering_protocol_layer
kb_name: Energy Metering Protocol and Object Layer
kb_version: 0.1.0
type: access_rights_model
layer: access_model
name: COSEM Access Rights Model
aliases:
- Get Set Action rights
- RC/PC/SC/LC access rights
keywords:
- access rights
- access rights rc/pc/sc/lc
- rc/pc/sc/lc
- r-/--
- rw/rw
- not allowed
- scope of access
domain_tags:
- access_control
- cosem_object
- configuration_check
---

# COSEM Access Rights Model

## Definition

Model for defining whether each client role can read attributes, write attributes, or invoke methods on COSEM objects.

## Aliases

- Get Set Action rights
- RC/PC/SC/LC access rights

## Domain Tags

- `access_control`
- `cosem_object`
- `configuration_check`

## Structured Data

```json metadata
{
  "rights": [
    {
      "code": "R-",
      "meaning": "read allowed"
    },
    {
      "code": "RW",
      "meaning": "read and write allowed"
    },
    {
      "code": "--",
      "meaning": "access not allowed"
    }
  ],
  "client_columns": [
    {
      "code": "RC",
      "meaning": "remote management and measurement client"
    },
    {
      "code": "PC",
      "meaning": "read client"
    },
    {
      "code": "SC",
      "meaning": "service/local or specialized client depending on table context"
    },
    {
      "code": "LC",
      "meaning": "local management and measurement client"
    }
  ]
}
```

## Notes

