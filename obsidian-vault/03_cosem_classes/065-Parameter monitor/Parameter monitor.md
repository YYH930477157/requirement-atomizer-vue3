---
id: KB-L3-IC-65-PARAMETER-MONITOR
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Parameter monitor
aliases:
- class 65
- CL 65
keywords:
- parameter monitor
- class 65
- cl 65
- changed_parameter
- capture_time
- parameter_list
- parameter_list_name
- hash_algorithm_id
- parameter_value_digest
- parameter_values
domain_tags:
- cosem_class
- control
- monitoring
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Parameter monitor

## Definition

COSEM interface class (class_id = 65, version = 1) for monitoring configuration changes. Holds parameter_list_name, hash_algorithm_id, parameter_value_digest, and parameter values so clients can detect configuration drift via digest comparison. Cardinality 0...n.

## Aliases

- class 65
- CL 65

## Domain Tags

- `cosem_class`
- `control`
- `monitoring`

## Access Semantics

logical_name and the static config attributes (parameter_list, parameter_list_name, hash_algorithm_id) are read-write (RW) via the SET service by an authorised management client; logical_name is read-only for all. The dynamic attributes (changed_parameter, capture_time, parameter_value_digest, parameter_values) are read-only (R) — they reflect runtime state populated by the server. parameter_list is managed via add_parameter/delete_parameter methods.

## Behavior Notes

- Parameter monitor supports configuration-change detection for a defined list of COSEM attributes. Cardinality 0...n.
- **changed_parameter** (attr 2): dynamic, structure {class_id, logical_name, attribute_index, attribute_value} of the most recently changed parameter.
- **capture_time** (attr 3): dynamic date-time of the most recent change.
- **parameter_list** (attr 4): static array of monitored parameter references {class_id, logical_name, attribute_index}. Managed via add/delete methods.
- **parameter_list_name** (attr 5): static octet-string name of the parameter list.
- **hash_algorithm_id** (attr 6): static enum, the hash algorithm used for the digest.
- **parameter_value_digest** (attr 7): dynamic octet-string, hash of parameter values in parameter_list order. Clients compare this to detect drift before reading parameter_values.
- **parameter_values** (attr 8): dynamic structure of A-XDR encoded copies of referenced attributes. May be captured into Profile generic buffers.

## Methods

- **add_parameter** (method 1): add one parameter reference to parameter_list (param: parameter_list_element).
- **delete_parameter** (method 2): delete one parameter reference from parameter_list (param: parameter_list_element).

## Structured Data

```json metadata
{
  "class_id": 65,
  "version": 1,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "changed_parameter", "type": "structure", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x08"},
    {"attribute_id": 3, "name": "capture_time", "type": "date-time", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x10"},
    {"attribute_id": 4, "name": "parameter_list", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x18"},
    {"attribute_id": 5, "name": "parameter_list_name", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x20"},
    {"attribute_id": 6, "name": "hash_algorithm_id", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x28"},
    {"attribute_id": 7, "name": "parameter_value_digest", "type": "octet-string", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x30"},
    {"attribute_id": 8, "name": "parameter_values", "type": "structure", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x38"}
  ],
  "methods": [
    {"method_id": 1, "name": "add_parameter", "parameter_type": "parameter_list_element", "short_name": "0x40", "meaning": "Add one parameter reference to parameter_list."},
    {"method_id": 2, "name": "delete_parameter", "parameter_type": "parameter_list_element", "short_name": "0x48", "meaning": "Delete one parameter reference from parameter_list."}
  ],
  "access_semantics": [
    "logical_name and static config attributes (parameter_list, parameter_list_name, hash_algorithm_id) are RW via SET by management client; logical_name read-only for all.",
    "Dynamic attributes (changed_parameter, capture_time, parameter_value_digest, parameter_values) are read-only (R) — reflect runtime state.",
    "parameter_list defines the monitored class_id, logical_name, and attribute_index references; managed via add/delete methods.",
    "parameter_value_digest lets clients compare a known configuration snapshot before reading parameter_values."
  ],
  "behavior_notes": [
    "Parameter monitor supports configuration-change detection for a defined list of COSEM attributes. Cardinality 0...n.",
    "changed_parameter/capture_time report the most recent change (dynamic, read-only).",
    "The digest is calculated over parameter values in parameter_list order using hash_algorithm_id.",
    "parameter_values holds A-XDR encoded copies of referenced attributes and may be captured into Profile generic buffers."
  ],
  "common_instances": [
    {"name": "Configuration parameter monitor", "obis": "implementation-specific"}
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.5.10 Parameter monitor (class_id = 65, version = 1)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.5.10. Full attributes with access_rights (dynamic R vs static RW), methods, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.5.10 (page 200-201).
- Digest comparison lets clients detect config drift before reading full parameter_values.
