---
id: KB-L3-IC-113-CHARGE
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Charge
aliases:
- class 113
- CL 113
keywords:
- charge
- class 113
- cl 113
- total_amount_paid
- charge_type
- priority
- unit_charge_active
- unit_charge_passive
- period
- charge_configuration
- last_collection_time
- total_amount_remaining
- proportion
domain_tags:
- cosem_class
- payment_metering
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Charge

## Definition

COSEM interface class (class_id = 113, version = 0) for managing a single Charge in payment metering. Depending on configured attributes (amount per price, period), the Charge is taken at appropriate times from the "Credit" object in use. All Charges for one supply are referenced in the Account's charge_reference_list. Cardinality 0...n.

## Aliases

- class 113
- CL 113

## Domain Tags

- `cosem_class`
- `payment_metering`

## Access Semantics

logical_name and the static configuration attributes (charge_type, priority, unit_charge_active/passive, unit_charge_activation_time, period, charge_configuration, proportion) are read-write (RW) via the SET service by an authorised management client; logical_name is read-only for all. The dynamic attributes (total_amount_paid, last_collection_time, last_collection_amount, total_amount_remaining) are read-only (R) — they reflect runtime charge-collection state.

## Behavior Notes

- Charge manages a single charge, taken from the Credit object in use at appropriate times. Cardinality 0...n; referenced in Account.charge_reference_list.
- **total_amount_paid** (attr 2): dynamic double-long, cumulative paid amount.
- **charge_type** (attr 3): static enum — collection type (time-based / consumption-based / payment-event-based).
- **priority** (attr 4): static unsigned, charge-collection priority.
- **unit_charge_active / unit_charge_passive** (attr 5/6): static structures, active and passive unit-charge definitions (amount per price).
- **unit_charge_activation_time** (attr 7): static octet-string, when passive becomes active.
- **period** (attr 8): static double-long-unsigned, relates to time-based and consumption-based collection.
- **charge_configuration** (attr 9): static bit-string of configuration flags.
- **last_collection_time / last_collection_amount** (attr 10/11): dynamic, most recent collection.
- **total_amount_remaining** (attr 12): dynamic double-long, outstanding charge.
- **proportion** (attr 13): static long-unsigned, relates to payment-event-based collection.

## Methods

- **update_unit_charge** (method 1): update the unit charge (param: data). Optional.
- **activate_passive_unit_charge** (method 2): activate the passive unit charge (param: data). Optional.
- **collect** (method 3): collect the charge (param: data). Optional; time-based and payment-event-based.
- **update_total_amount_remaining** (method 4): update total_amount_remaining (param: data). Optional; payment-event-based.
- **set_total_amount_remaining** (method 5): set total_amount_remaining (param: data). Optional; payment-event-based.

## Structured Data

```json metadata
{
  "class_id": 113,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "total_amount_paid", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x08"},
    {"attribute_id": 3, "name": "charge_type", "type": "enum", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"},
    {"attribute_id": 4, "name": "priority", "type": "unsigned", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x18"},
    {"attribute_id": 5, "name": "unit_charge_active", "type": "structure", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x20"},
    {"attribute_id": 6, "name": "unit_charge_passive", "type": "structure", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x28"},
    {"attribute_id": 7, "name": "unit_charge_activation_time", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x30"},
    {"attribute_id": 8, "name": "period", "type": "double-long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x38"},
    {"attribute_id": 9, "name": "charge_configuration", "type": "bit-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x40"},
    {"attribute_id": 10, "name": "last_collection_time", "type": "date-time", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x48"},
    {"attribute_id": 11, "name": "last_collection_amount", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x50"},
    {"attribute_id": 12, "name": "total_amount_remaining", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x58"},
    {"attribute_id": 13, "name": "proportion", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x60"}
  ],
  "methods": [
    {"method_id": 1, "name": "update_unit_charge", "parameter_type": "data", "mandatory": false, "short_name": "0x68", "meaning": "Update the unit charge."},
    {"method_id": 2, "name": "activate_passive_unit_charge", "parameter_type": "data", "mandatory": false, "short_name": "0x70", "meaning": "Activate the passive unit charge."},
    {"method_id": 3, "name": "collect", "parameter_type": "data", "mandatory": false, "short_name": "0x78", "meaning": "Collect the charge (time-based/payment-event-based)."},
    {"method_id": 4, "name": "update_total_amount_remaining", "parameter_type": "data", "mandatory": false, "short_name": "0x80", "meaning": "Update total_amount_remaining (payment-event-based)."},
    {"method_id": 5, "name": "set_total_amount_remaining", "parameter_type": "data", "mandatory": false, "short_name": "0x88", "meaning": "Set total_amount_remaining (payment-event-based)."}
  ],
  "access_semantics": [
    "logical_name and static config (charge_type, priority, unit charges, period, configuration, proportion) are RW via SET by management client; logical_name read-only for all.",
    "Dynamic collection-state attributes (total_amount_paid, last_collection_time/amount, total_amount_remaining) are read-only (R).",
    "Charge is taken from the Credit object in use; referenced in Account.charge_reference_list."
  ],
  "behavior_notes": [
    "Charge manages a single charge taken from the Credit in use. Cardinality 0...n.",
    "charge_type enum: time-based / consumption-based / payment-event-based collection.",
    "unit_charge_active/passive + activation_time support tariff switching.",
    "period relates to time-based/consumption-based collection; proportion to payment-event-based.",
    "collect/update/set_total_amount_remaining methods drive the collection cycle."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.6.4 Charge (class_id = 113, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.6.4. Full 13 attributes with access_rights (dynamic R vs static RW), 5 methods, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.6.4 (page 236-237).
- Collection-cycle details may be project-dependent (affects third-party value estimates).
