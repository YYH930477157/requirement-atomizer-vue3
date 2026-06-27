---
id: KB-OBIS-0-0-10-0-0-255-GLOBAL-METER-RESET
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Global Meter Reset
aliases:
- Global Meter Reset 0-0:10.0.0.255
- Global meter reset script table
keywords:
- 0-0:10.0.0.255
- Global Meter Reset
- global meter reset script
- reset parameters and registers
domain_tags:
- cosem_object
- script
- reset
- meter_function
relations:
- relation: instance_of
  target: KB-L3-IC-9-SCRIPT-TABLE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Global Meter Reset

## Definition

Row-level Script Table object for global meter reset actions at logical name `0-0:10.0.0.255`.

## Aliases

- Global Meter Reset 0-0:10.0.0.255
- Global meter reset script table

## Domain Tags

- `cosem_object`
- `script`
- `reset`
- `meter_function`

## Relations

- `instance_of` -> `KB-L3-IC-9-SCRIPT-TABLE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:10.0.0.255",
  "likely_interface_class_id": 9,
  "likely_interface_class_name": "Script Table",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "10 Script Table",
    "D": "0 predefined script group",
    "E": "0 global meter reset script",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    },
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "Script Table interface class"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Global Meter Reset at 0-0:10.0.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching reset scripts that clear parameters, registers, or meter-wide state.",
    "ABNT Appendix 9 describes this instance as resetting parameters and registers."
  ]
}
```

## Notes
