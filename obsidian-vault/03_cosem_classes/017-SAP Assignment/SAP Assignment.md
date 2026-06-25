---
id: KB-L3-IC-17-SAP-ASSIGNMENT
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: SAP Assignment
aliases:
- class 17
- CL 17
keywords:
- class 17
- cl 17
- sap assignment
- sap_assignment_list
domain_tags:
- cosem_class
- association
- logical_device
---

# SAP Assignment

## Definition

COSEM interface class listing SAP assignments for logical devices.

## Aliases

- class 17
- CL 17

## Domain Tags

- `cosem_class`
- `association`
- `logical_device`

## Structured Data

```json metadata
{
  "class_id": 17,
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
      "name": "SAP_assignment_list",
      "type": "array",
      "mandatory": true,
      "storage": "static"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "connect_logical_device",
      "parameter_type": "long-unsigned logical_device_id",
      "meaning": "Connect or announce one logical device SAP assignment."
    },
    {
      "method_id": 2,
      "name": "disconnect_logical_device",
      "parameter_type": "long-unsigned logical_device_id",
      "meaning": "Disconnect or remove one logical device SAP assignment."
    }
  ],
  "access_semantics": [
    "SAP_assignment_list maps logical device identifiers to logical device names.",
    "The object is typically in the management logical device when a physical device hosts more than one logical device.",
    "Association and wrapper-port binding logic can depend on SAP assignment when resolving logical devices."
  ],
  "behavior_notes": [
    "SAP Assignment provides the logical-device discovery list used before clients select an application association.",
    "In TCP-UDP/IP profiles, application processes are bound through wrapper ports and logical device SAP assignments.",
    "ABNT Appendix 9 exposes this instance at 0-0:41.0.0.255 with SAP_assignment_list readable by all configured client classes."
  ],
  "common_instances": [
    {
      "name": "SAP Assignment",
      "obis": "0-0:41.0.0.255"
    }
  ],
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.4.5 SAP assignment (class_id = 17, version = 0)"
    },
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    }
  ]
}
```

## Notes

