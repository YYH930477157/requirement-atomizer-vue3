---
id: KB-L3-IC-62-COMPACT-DATA
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Compact Data
aliases:
- Compact data object
- class 62
- CL 62
keywords:
- compact data
- class 62
- cl 62
- compact_buffer
- template_id
- template_description
- capture_objects
- selective access
- restriction_element
domain_tags:
- cosem_class
- measurement_data
- profile_data
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Compact Data

## Definition

COSEM interface class for compact storage and transfer of captured values using a template description and compact buffer representation.

## Aliases

- Compact data object
- class 62
- CL 62

## Domain Tags

- `cosem_class`
- `measurement_data`
- `profile_data`

## Structured Data

```json metadata
{
  "class_id": 62,
  "version": 1,
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "mandatory": true, "storage": "static"},
    {"attribute_id": 2, "name": "compact_buffer", "type": "octet-string", "mandatory": true, "storage": "dynamic"},
    {"attribute_id": 3, "name": "capture_objects", "type": "array", "mandatory": true, "storage": "static"},
    {"attribute_id": 4, "name": "template_id", "type": "unsigned", "mandatory": true, "storage": "static"},
    {"attribute_id": 5, "name": "template_description", "type": "octet-string", "mandatory": true, "storage": "dynamic"},
    {"attribute_id": 6, "name": "capture_method", "type": "enum", "mandatory": true, "storage": "static"}
  ],
  "methods": [
    {"method_id": 1, "name": "reset", "parameter_type": "integer(0)"},
    {"method_id": 2, "name": "capture", "parameter_type": "integer(0)"}
  ],
  "behavior_notes": [
    "capture_objects lists the COSEM object attributes captured into compact_buffer.",
    "template_id and template_description let a client reconstruct uncompacted attribute descriptors, data types, and values.",
    "The template_id attribute shall be the first element in capture_objects.",
    "Relative and absolute selective access mechanisms are mutually exclusive for captured Profile generic buffers."
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.3.10 Compact data (class_id = 62, version = 1)"
    }
  ]
}
```

## Notes
