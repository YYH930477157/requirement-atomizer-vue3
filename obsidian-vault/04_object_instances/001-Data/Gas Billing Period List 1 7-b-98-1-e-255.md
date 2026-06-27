---
id: KB-OBIS-7-B-98-1-E-255-GAS-BILLING-LIST-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas billing period list 1
aliases:
- Gas billing list 1
- Gas meter billing period list 1
- OBIS 7-b:98.1.e.255
keywords:
- 7-b:98.1.e.255
- gas billing period list 1
- gas billing list
- gas list object
domain_tags:
- cosem_object
- gas
- billing
- list_object
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-63
---

# Gas billing period list 1

## Definition

Pattern-level row entry for gas billing period list objects, represented by OBIS pattern `7-b:98.1.e.255`.

## Aliases

- Gas billing list 1
- Gas meter billing period list 1
- OBIS 7-b:98.1.e.255

## Domain Tags

- `cosem_object`
- `gas`
- `billing`
- `list_object`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-63`

## Structured Data

```json metadata
{
  "obis_pattern": "7-b:98.1.e.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "b channel selector",
    "C": "98 list objects",
    "D": "1 billing period list 1",
    "E": "e list selector",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 63,
    "title": "OBIS codes for list objects - Gas"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 63 list objects - Gas"
    }
  ],
  "applicable_notes": [
    "Use this pattern for gas list objects that hold billing-period data.",
    "The B and E groups select the concrete channel and list variant."
  ]
}
```

## Notes

