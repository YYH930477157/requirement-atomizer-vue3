---
id: KB-L3-IC-153-COAP-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: CoAP diagnostic
aliases:
- class 153
- CL 153
keywords:
- coap diagnostic
- class 153
- cl 153
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# CoAP diagnostic

## Definition

COSEM interface class for exposing CoAP diagnostic diagnostic, status, or counter information.

## Aliases

- class 153
- CL 153

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 153,
  "version": 0,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    }
  ],
  "methods": [],
  "coverage_level": "catalogue_seed",
  "coverage_note": "Seeded from the Blue Book Part 2 current interface class catalogue; attribute and method details should be expanded during detailed knowledge-base enrichment."
}
```

## Notes
