---
id: KB-OBIS-7-0-13-4-0-255-GAS-CONVERSION-FACTOR-AVERAGE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas conversion factor average
aliases:
- Average gas conversion factor
- Gas volume conversion factor average
- OBIS 7-0:13.4.0.255
keywords:
- 7-0:13.4.0.255
- gas conversion factor average
- average gas conversion factor
- gas conversion process
domain_tags:
- cosem_object
- gas
- conversion
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-50
---

# Gas conversion factor average

## Definition

Pattern-level OBIS object for an average gas conversion process factor, represented by logical name pattern `7-0:13.4.0.255`.

## Aliases

- Average gas conversion factor
- Gas volume conversion factor average
- OBIS 7-0:13.4.0.255

## Domain Tags

- `cosem_object`
- `gas`
- `conversion`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-50`

## Structured Data

```json metadata
{
  "obis_pattern": "7-0:13.4.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "0 no channel",
    "C": "13 gas conversion factor",
    "D": "4 average value",
    "E": "0 total or default selector",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 50,
    "title": "OBIS codes of the main objects in the gas conversion process data flow"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 50 gas conversion process data flow"
    }
  ],
  "applicable_notes": [
    "Pattern-level representative for the average gas conversion process factor.",
    "Use gas C/D/E value-group tables to resolve the exact conversion quantity and averaging semantics."
  ]
}
```

## Notes
