---
id: KB-OBIS-1-0-2-6-X-255-MAXIMUM-ACTIVE-DEMAND-EXPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Maximum Active Demand Register export (-A)
aliases:
- Maximum active export demand 1-0:2.6.x.255
- Maximum Active Demand Register export
- Maximum demand export -A
keywords:
- 1-0:2.6.x.255
- Maximum Active Demand Register export
- maximum active export demand
- maximum demand -A
domain_tags:
- cosem_object
- ac_electricity
- active_power
- extended_register
- maximum_demand
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Maximum Active Demand Register export (-A)

## Definition

Row-level Extended Register object for maximum active export demand (-A) over a billing period, represented by OBIS `1-0:2.6.x.255`.

## Aliases

- Maximum active export demand 1-0:2.6.x.255
- Maximum demand export -A

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `active_power`
- `extended_register`
- `maximum_demand`

## Relations

- `instance_of` -> `KB-L3-IC-4-EXTENDED-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:2.6.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 aggregate channel",
    "C": "2 active power- / active energy export direction",
    "D": "6 maximum demand value for billing period",
    "E": "x tariff or rate period",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 14,
    "title": "Value group D codes - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 14 AC electricity D codes; C=2, D=6 maximum value"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Maximum Active Demand Register export (-A) at 1-0:2.6.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row for maximum active export demand requirements using Extended Register semantics.",
    "Extended Register adds capture_time and status around the maximum demand value."
  ]
}
```

## Notes

