---
id: KB-L3-IC-112-CREDIT
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Credit
aliases:
- class 112
- CL 112
keywords:
- credit
- class 112
- cl 112
- current_credit_amount
- credit_type
- priority
- warning_threshold
- limit
- credit_configuration
- credit_status
- preset_credit_amount
- period
domain_tags:
- cosem_class
- payment_metering
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Credit

## Definition

COSEM interface class (class_id = 112, version = 0) representing a single credit object in payment metering. Each Credit object holds a current amount, type (token/reserved/emergency/time-based/consumption-based), priority, thresholds, and contributes to the Account's available_credit. Cardinality 0...n.

## Aliases

- class 112
- CL 112

## Domain Tags

- `cosem_class`
- `payment_metering`

## Access Semantics

logical_name and the static configuration attributes (credit_type, priority, warning_threshold, limit, credit_configuration, preset_credit_amount, credit_available_threshold, period) are read-write (RW) via the SET service by an authorised management client; logical_name is read-only for all. The dynamic attributes (current_credit_amount, credit_status) are read-only (R) — they reflect runtime credit state updated by methods, top-ups, and charge collection.

## Behavior Notes

- Credit represents one credit object in payment metering. current_credit_amount contributes to the referencing Account's available_credit. Cardinality 0...n.
- **current_credit_amount** (attr 2): dynamic double-long, the credit value. Increased/decreased by methods, top-ups, charge collection. Scaled per Account currency. Default 0.
- **credit_type** (attr 3): static enum — (0) token_credit, (1) reserved_credit, (2) emergency_credit, (3) time-based credit, (4) consumption-based credit. Determines which attributes are processed.
- **priority** (attr 4): static unsigned, credit usage priority.
- **warning_threshold** (attr 5): static double-long.
- **limit** (attr 6): static double-long, credit ceiling.
- **credit_configuration** (attr 7): static bit-string of configuration flags.
- **credit_status** (attr 8): dynamic enum, runtime credit status.
- **preset_credit_amount** (attr 9): static double-long, applies to emergency/some time-based/consumption-based credits.
- **credit_available_threshold** (attr 10): static double-long.
- **period** (attr 11): static date-time, applies to time-based and consumption-based credit.

## Methods

- **update_amount** (method 1): update current_credit_amount (param: data). Optional.
- **set_amount_to_value** (method 2): set current_credit_amount to a value (param: data). Optional.
- **invoke_credit** (method 3): invoke the credit (param: data). Optional; applies to emergency/time-based/consumption-based credits.

## Structured Data

```json metadata
{
  "class_id": 112,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "current_credit_amount", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "default": 0, "short_name": "0x08"},
    {"attribute_id": 3, "name": "credit_type", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "priority", "type": "unsigned", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x18"},
    {"attribute_id": 5, "name": "warning_threshold", "type": "double-long", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x20"},
    {"attribute_id": 6, "name": "limit", "type": "double-long", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x28"},
    {"attribute_id": 7, "name": "credit_configuration", "type": "bit-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x30"},
    {"attribute_id": 8, "name": "credit_status", "type": "enum", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x38"},
    {"attribute_id": 9, "name": "preset_credit_amount", "type": "double-long", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x40"},
    {"attribute_id": 10, "name": "credit_available_threshold", "type": "double-long", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x48"},
    {"attribute_id": 11, "name": "period", "type": "date-time", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x50"}
  ],
  "methods": [
    {"method_id": 1, "name": "update_amount", "parameter_type": "data", "mandatory": false, "short_name": "0x58", "meaning": "Update current_credit_amount."},
    {"method_id": 2, "name": "set_amount_to_value", "parameter_type": "data", "mandatory": false, "short_name": "0x60", "meaning": "Set current_credit_amount to a value."},
    {"method_id": 3, "name": "invoke_credit", "parameter_type": "data", "mandatory": false, "short_name": "0x68", "meaning": "Invoke the credit (emergency/time-based/consumption-based)."}
  ],
  "enum_definitions": {
    "credit_type": {"0": "token_credit", "1": "reserved_credit", "2": "emergency_credit", "3": "time-based credit", "4": "consumption-based credit"}
  },
  "access_semantics": [
    "logical_name and static config (credit_type, priority, thresholds, limit, configuration, period) are RW via SET by management client; logical_name read-only for all.",
    "Dynamic attributes (current_credit_amount, credit_status) are read-only (R) — updated by methods, top-ups, charge collection.",
    "current_credit_amount contributes to the referencing Account's available_credit."
  ],
  "behavior_notes": [
    "Credit represents one credit object in payment metering. Cardinality 0...n.",
    "current_credit_amount: dynamic, scaled per Account currency; updated by methods/top-ups/charges.",
    "credit_type enum: token/reserved/emergency/time-based/consumption-based; determines which attributes are processed.",
    "preset_credit_amount applies to emergency and some time-based/consumption-based credits.",
    "period applies to time-based and consumption-based credit."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.6.3 Credit (class_id = 112, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.6.3. Full 11 attributes with access_rights (dynamic R vs static RW), 3 methods, credit_type enum, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.6.3 (page 229-230).
- current_credit_amount scaled per Account currency attribute.
