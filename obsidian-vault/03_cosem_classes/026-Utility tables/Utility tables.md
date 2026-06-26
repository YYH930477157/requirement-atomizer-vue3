---
id: KB-L3-IC-26-UTILITY-TABLES
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Utility tables
aliases:
- class 26
- CL 26
- utility table object
- table object
keywords:
- utility tables
- class 26
- cl 26
- table_cell_values
- table_active_axis
- table passive axis
- utility table buffer
domain_tags:
- cosem_class
- measurement_data
- table_model
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Utility tables

## Definition

COSEM interface class for representing compact utility-defined tables whose cells are addressed through active and passive axes.

## Aliases

- class 26
- CL 26
- utility table object
- table object

## Domain Tags

- `cosem_class`
- `measurement_data`
- `table_model`

## Structured Data

```json metadata
{
  "class_id": 26,
  "version": 0,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "access": "R",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "table_cell_values",
      "type": "array",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Table payload values arranged according to the active and passive axis definitions"
    },
    {
      "attribute_id": 3,
      "name": "table_active_axis",
      "type": "structure",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Definition of the active axis used to address or interpret rows, columns, or intervals"
    },
    {
      "attribute_id": 4,
      "name": "table_passive_axis",
      "type": "structure",
      "access": "R/W",
      "mandatory": true,
      "meaning": "Definition of the passive axis used together with the active axis to interpret table cells"
    }
  ],
  "methods": [],
  "access_semantics": [
    "table_cell_values is the main data payload and should be interpreted only with the matching active and passive axis definitions.",
    "Axis attributes are configuration data; changing them changes the meaning of the stored table values and should be restricted to authorized clients."
  ],
  "behavior_notes": [
    "Use this class when requirements mention utility-defined tables, tabular measurement data, active axis, passive axis, or addressed table cells.",
    "Requirements involving Utility tables should preserve both table value constraints and axis interpretation constraints; a cell value alone is usually insufficient for implementation."
  ],
  "source_refs": [
    {
      "standard": "DLMS UA Blue Book Part 2",
      "section": "4.3.7 Utility tables (class_id = 26, version = 0)"
    }
  ],
  "coverage_level": "enriched",
  "coverage_note": "Expanded with table payload, axis configuration, and implementation semantics."
}
```

## Notes

- Keep Utility tables grouped with table-oriented measurement data rather than generic register values.
