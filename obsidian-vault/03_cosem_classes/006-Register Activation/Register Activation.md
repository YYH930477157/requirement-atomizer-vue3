---
id: KB-L3-IC-6-REGISTER-ACTIVATION
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Register Activation
aliases:
- class 6
- CL 6
keywords:
- class 6
- cl 6
- register activation
- active_mask
- register_assignment
domain_tags:
- cosem_class
- billing_profile
- tariff_calendar
---

# Register Activation

## Definition

COSEM class used to define active register masks and register assignments.

## Aliases

- class 6
- CL 6

## Domain Tags

- `cosem_class`
- `billing_profile`
- `tariff_calendar`

## Structured Data

```json metadata
{
  "class_id": 6,
  "version": 0,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 2,
      "name": "register_assignment",
      "type": "array",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 3,
      "name": "mask_list",
      "type": "array",
      "mandatory": true,
      "storage": "static"
    },
    {
      "attribute_id": 4,
      "name": "active_mask",
      "type": "octet-string",
      "mandatory": true,
      "storage": "dynamic"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "add_register",
      "parameter_type": "structure {class_id, logical_name}",
      "meaning": "Append one Register, Extended register, or Demand register object to register_assignment."
    },
    {
      "method_id": 2,
      "name": "add_mask",
      "parameter_type": "register_act_mask",
      "meaning": "Add or overwrite one activation mask in mask_list."
    },
    {
      "method_id": 3,
      "name": "delete_mask",
      "parameter_type": "octet-string mask_name",
      "meaning": "Delete one activation mask identified by mask_name."
    }
  ],
  "access_semantics": [
    "register_assignment and mask_list are static configuration data; active_mask is dynamic and selects the currently enabled subset.",
    "add_register, add_mask, and delete_mask are action methods used to maintain tariff mask configuration without rewriting the whole object.",
    "Changing active_mask changes which assigned registers participate in the currently active tariff structure."
  ],
  "behavior_notes": [
    "A Register activation object groups Register, Extended register, or Demand register instances for tariff handling.",
    "Each mask in mask_list contains indices into register_assignment; the first assigned register is referenced by index 1.",
    "active_mask names the mask that is currently active; registers assigned to the object but not included in the active mask are disabled.",
    "Registers not included in any Register activation object's register_assignment remain enabled by default."
  ],
  "common_instances": [
    {
      "name": "Register activation",
      "obis": "0-0:14.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.3.5 Register activation (class_id = 6, version = 0)"
    }
  ]
}
```

## Notes

