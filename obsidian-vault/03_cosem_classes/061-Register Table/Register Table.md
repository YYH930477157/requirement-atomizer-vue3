---
id: KB-L3-IC-61-REGISTER-TABLE
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Register Table
aliases:
- Register table object
- class 61
- CL 61
keywords:
- register table
- class 61
- cl 61
- table_cell_values
- table_cell_definition
- scaler_unit
- capture
- group_E_values
domain_tags:
- cosem_class
- register
- measurement_data
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Register Table

## Definition

COSEM interface class for representing register values in a table-oriented structure, typically used where related measured values are arranged as rows and columns.

## Aliases

- Register table object
- class 61
- CL 61

## Domain Tags

- `cosem_class`
- `register`
- `measurement_data`

## Structured Data

```json metadata
{
  "class_id": 61,
  "version": 0,
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "mandatory": true},
    {"attribute_id": 2, "name": "table_cell_values", "type": "compact-array or array", "mandatory": true, "storage": "dynamic"},
    {"attribute_id": 3, "name": "table_cell_definition", "type": "structure", "mandatory": true, "storage": "static"},
    {"attribute_id": 4, "name": "scaler_unit", "type": "scaler_unit_type", "mandatory": true, "storage": "static"}
  ],
  "methods": [
    {"method_id": 1, "name": "reset", "parameter_type": "integer(0)", "meaning": "Clear table_cell_values without changing captured attributes"},
    {"method_id": 2, "name": "capture", "parameter_type": "integer(0)", "meaning": "Copy configured attribute values into table_cell_values"}
  ],
  "behavior_notes": [
    "table_cell_definition defines the common class_id, logical_name wildcard, group_E_values, and attribute_index for captured attributes.",
    "Changing table_cell_definition automatically resets table_cell_values and propagates to profiles that capture this object.",
    "When capturing Register or Extended register value attributes, scaler_unit is common for all objects and holds a copy."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.3.8 Register table (class_id = 61, version = 0)"
    }
  ]
}
```

## Notes
