---
id: KB-OBIS-1-0-1-2-X-255-CUMULATIVE-ACTIVE-DEMAND-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Cumulative Active Demand Register import (+A)
aliases:
- Cumulative active import demand 1-0:1.2.x.255
- Cumulative Active Demand Register import
- Cumulative demand import +A
keywords:
- 1-0:1.2.x.255
- Cumulative Active Demand Register import
- cumulative active import demand
- cumulative demand +A
domain_tags:
- cosem_object
- ac_electricity
- active_power
- extended_register
- cumulative_demand
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Cumulative Active Demand Register import (+A)

## Definition

Row-level Extended Register object for cumulative active import demand (+A), represented by OBIS `1-0:1.2.x.255`.

## Aliases

- Cumulative active import demand 1-0:1.2.x.255
- Cumulative demand import +A

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `active_power`
- `extended_register`
- `cumulative_demand`

## Relations

- `instance_of` -> `KB-L3-IC-4-EXTENDED-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:1.2.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 aggregate channel",
    "C": "1 active power+ / active energy import direction",
    "D": "2 cumulative maximum demand value",
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
      "section": "Table 14 AC electricity D codes; C=1, D=2 cumulative maximum"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Cumulative Active Demand Register import (+A) at 1-0:1.2.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row for cumulative active import demand requirements using Extended Register semantics.",
    "Extended Register adds capture_time and status around the cumulative demand value."
  ]
}
```

## Notes

