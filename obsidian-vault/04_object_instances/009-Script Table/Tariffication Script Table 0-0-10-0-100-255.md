---
id: KB-OBIS-0-0-10-0-100-255-TARIFFICATION-SCRIPT-TABLE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Tariffication script table
aliases:
- Tariffication script table 0-0:10.0.100.255
- Tariff script table
keywords:
- 0-0:10.0.100.255
- Tariffication script table
- tariff script table
- tariffication script
domain_tags:
- cosem_object
- script
- tariff
- billing_period
relations:
- relation: instance_of
  target: KB-L3-IC-9-SCRIPT-TABLE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Tariffication script table

## Definition

Row-level Script Table object for tariff-related actions at logical name `0-0:10.0.100.255`.

## Aliases

- Tariffication script table 0-0:10.0.100.255
- Tariff script table

## Domain Tags

- `cosem_object`
- `script`
- `tariff`
- `billing_period`

## Relations

- `instance_of` -> `KB-L3-IC-9-SCRIPT-TABLE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:10.0.100.255",
  "likely_interface_class_id": 9,
  "likely_interface_class_name": "Script Table",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "10 Script Table",
    "D": "0 predefined script group",
    "E": "100 tariffication script table",
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
      "section": "Tariffication script table at 0-0:10.0.100.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching tariff-switching, tariff activation, or tariff billing script requirements.",
    "The Script Table scripts attribute enumerates action specifications executed by this tariffication object."
  ]
}
```

## Notes
