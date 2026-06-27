---
id: KB-L3-IC-122-FUNCTION-CONTROL
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Function control
aliases:
- class 122
- CL 122
keywords:
- function control
- class 122
- cl 122
- logical_name
- activation_status
- function_list
- set_function_status
- add_function
- remove_function
domain_tags:
- cosem_class
- access_control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Function control

## Definition

COSEM interface class (class_id = 122, version = 0). Controls activation of metering functions: an activation status and a function list, with methods to enable/add/remove functions.

## Aliases

- class 122
- CL 122

## Domain Tags

- `cosem_class`
- `access_control`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Controls activation of metering functions: an activation status and a function list, with methods to enable/add/remove functions.
- Specific methods: set_function_status, add_function, remove_function.

## Structured Data

```json metadata
{
  "class_id": 122,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "mode": "static",
      "type": "octet-string"
    },
    {
      "attribute_id": 2,
      "name": "activation_status",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "function_list",
      "mode": "static",
      "type": "array",
      "short_name": "x + 0x10"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "set_function_status",
      "short_name": "x + 0x20"
    },
    {
      "method_id": 2,
      "name": "add_function",
      "short_name": "x + 0x28"
    },
    {
      "method_id": 3,
      "name": "remove_function",
      "short_name": "x + 0x30"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Controls activation of metering functions: an activation status and a function list, with methods to enable/add/remove functions.",
    "Specific methods: set_function_status, add_function, remove_function."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.4.10; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.4.10.
- 3 attributes, 3 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
