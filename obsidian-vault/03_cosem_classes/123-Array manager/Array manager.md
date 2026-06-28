---
id: KB-L3-IC-123-ARRAY-MANAGER
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Array manager
aliases:
- class 123
- CL 123
keywords:
- array manager
- class 123
- cl 123
- logical_name
- array_object_list
- retrieve_number_of_entries
- retrieve_entries
- insert_entry
- update_entry
- remove_entries
domain_tags:
- cosem_class
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Array manager

## Definition

COSEM interface class (class_id = 123, version = 0). Allows managing attributes of type array of other interface objects: retrieving the number of entries, selectively reading a range of entries, inserting/updating an entry, and removing a range of entries. Each instance manages several array attributes assigned to it.

## Aliases

- class 123
- CL 123

## Domain Tags

- `cosem_class`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- The array_object_list identifies (by class_id, logical_name and attribute_index) the arrays the instance manages; when a target array is accessed through an Array manager object, its own access rights are observed.
- Specific methods: retrieve_number_of_entries (mandatory), retrieve_entries (mandatory), insert_entry (optional), update_entry (optional), remove_entries (optional).

## Structured Data

```json metadata
{
  "class_id": 123,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "array_object_list", "mode": "static", "type": "array", "short_name": "x + 0x08" }
  ],
  "methods": [
    { "method_id": 1, "name": "retrieve_number_of_entries", "short_name": "x + 0x20" },
    { "method_id": 2, "name": "retrieve_entries", "short_name": "x + 0x28" },
    { "method_id": 3, "name": "insert_entry", "short_name": "x + 0x30" },
    { "method_id": 4, "name": "update_entry", "short_name": "x + 0x38" },
    { "method_id": 5, "name": "remove_entries", "short_name": "x + 0x40" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "The array_object_list identifies (by class_id, logical_name and attribute_index) the arrays the instance manages; when a target array is accessed through an Array manager object, its own access rights are observed.",
    "Specific methods: retrieve_number_of_entries (mandatory), retrieve_entries (mandatory), insert_entry (optional), update_entry (optional), remove_entries (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.4.11; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.4.11.
- 2 attributes, 5 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
