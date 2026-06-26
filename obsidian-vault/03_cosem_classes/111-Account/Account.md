---
id: KB-L3-IC-111-ACCOUNT
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Account
aliases:
- class 111
- CL 111
keywords:
- account
- class 111
- cl 111
- account_mode_and_status
- current_credit_in_use
- available_credit
- aggregated_debt
- credit_reference_list
- charge_reference_list
- currency
- low_credit_threshold
- max_provision
domain_tags:
- cosem_class
- payment_metering
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Account

## Definition

COSEM interface class (class_id = 111, version = 0) for payment metering. The Account object holds the payment mode/status, current credit in use, available credit, debt, and references to Credit/Charge/Token-gateway objects. Cardinality 0...n.

## Aliases

- class 111
- CL 111

## Domain Tags

- `cosem_class`
- `payment_metering`

## Access Semantics

logical_name and the static configuration attributes (clearance_threshold, credit/charge/token reference lists, credit_charge_configuration, account_activation/closure_time, currency, max_provision/period) are read-write (RW) via the SET service by an authorised management client; logical_name is read-only for all. The dynamic attributes (current_credit_in_use, current_credit_status, available_credit, amount_to_clear, aggregated_debt, low_credit_threshold, next_credit_available_threshold) are read-only (R) — they reflect runtime payment state.

## Behavior Notes

- Account holds payment metering state: payment mode/status, current credit, available credit, debt. Cardinality 0...n.
- **account_mode_and_status** (attr 2): structure {payment_mode: enum, status: enum}.
- **current_credit_in_use** (attr 3): dynamic unsigned, which credit is active.
- **current_credit_status** (attr 4): dynamic bit-string (all bits clear default).
- **available_credit** (attr 5): dynamic double-long, sum of referenced Credit objects' amounts minus debt. Default 0.
- **amount_to_clear** (attr 6): dynamic double-long, debt to clear before credit available. Default 0.
- **clearance_threshold** (attr 7): static double-long.
- **aggregated_debt** (attr 8): dynamic double-long, total debt. Default 0.
- **credit_reference_list / charge_reference_list / credit_charge_configuration / token_gateway_configuration** (attr 9-12): static arrays referencing Credit/Charge/Token-gateway objects.
- **account_activation_time / account_closure_time** (attr 13-14): static octet-string.
- **currency** (attr 15): static structure.
- **low_credit_threshold / next_credit_available_threshold** (attr 16-17): dynamic double-long.
- **max_provision / max_provision_period** (attr 18-19): static.

## Methods

- **activate_account** (method 1): activate the account (param: data). Optional.
- **close_account** (method 2): close the account (param: data). Optional.
- **reset_account** (method 3): reset the account (param: data). Optional.

## Structured Data

```json metadata
{
  "class_id": 111,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "account_mode_and_status", "type": "structure", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x08"},
    {"attribute_id": 3, "name": "current_credit_in_use", "type": "unsigned", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x10"},
    {"attribute_id": 4, "name": "current_credit_status", "type": "bit-string", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x18"},
    {"attribute_id": 5, "name": "available_credit", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "default": 0, "short_name": "0x20"},
    {"attribute_id": 6, "name": "amount_to_clear", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "default": 0, "short_name": "0x28"},
    {"attribute_id": 7, "name": "clearance_threshold", "type": "double-long", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x30"},
    {"attribute_id": 8, "name": "aggregated_debt", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "default": 0, "short_name": "0x38"},
    {"attribute_id": 9, "name": "credit_reference_list", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "default": [], "short_name": "0x40"},
    {"attribute_id": 10, "name": "charge_reference_list", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "default": [], "short_name": "0x48"},
    {"attribute_id": 11, "name": "credit_charge_configuration", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "default": [], "short_name": "0x50"},
    {"attribute_id": 12, "name": "token_gateway_configuration", "type": "array", "static": true, "mandatory": true, "access_rights": "RW", "default": [], "short_name": "0x58"},
    {"attribute_id": 13, "name": "account_activation_time", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x60"},
    {"attribute_id": 14, "name": "account_closure_time", "type": "octet-string", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x68"},
    {"attribute_id": 15, "name": "currency", "type": "structure", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x70"},
    {"attribute_id": 16, "name": "low_credit_threshold", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "default": 0, "short_name": "0x78"},
    {"attribute_id": 17, "name": "next_credit_available_threshold", "type": "double-long", "dynamic": true, "mandatory": true, "access_rights": "R", "default": 0, "short_name": "0x80"},
    {"attribute_id": 18, "name": "max_provision", "type": "long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "default": 0, "short_name": "0x88"},
    {"attribute_id": 19, "name": "max_provision_period", "type": "double-long", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x90"}
  ],
  "methods": [
    {"method_id": 1, "name": "activate_account", "parameter_type": "data", "mandatory": false, "short_name": "0x98", "meaning": "Activate the account."},
    {"method_id": 2, "name": "close_account", "parameter_type": "data", "mandatory": false, "short_name": "0xA0", "meaning": "Close the account."},
    {"method_id": 3, "name": "reset_account", "parameter_type": "data", "mandatory": false, "short_name": "0xA8", "meaning": "Reset the account."}
  ],
  "access_semantics": [
    "logical_name and static config (reference lists, thresholds, currency, activation/closure time, max_provision) are RW via SET by management client; logical_name read-only for all.",
    "Dynamic payment-state attributes (current_credit_in_use/status, available_credit, amount_to_clear, aggregated_debt, low/next credit thresholds) are read-only (R).",
    "available_credit = sum of referenced Credit objects' amounts minus aggregated_debt."
  ],
  "behavior_notes": [
    "Account holds payment metering state. Cardinality 0...n.",
    "account_mode_and_status: {payment_mode enum, status enum}.",
    "available_credit/aggregated_debt/amount_to_clear are dynamic runtime payment state.",
    "credit/charge/token reference lists link to Credit(112)/Charge(113)/Token-gateway(115) objects.",
    "activate/close/reset_account methods manage account lifecycle."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.6.2 Account (class_id = 111, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.6.2. Full 19 attributes with access_rights (dynamic R vs static RW), 3 lifecycle methods, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.6.2 (page 216-217).
- available_credit is scaled per the Account currency attribute.
