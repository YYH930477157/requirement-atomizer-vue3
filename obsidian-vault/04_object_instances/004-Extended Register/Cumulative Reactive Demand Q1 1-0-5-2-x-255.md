---
id: KB-OBIS-1-0-5-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Cumulative Reactive Demand Register import (Q1)
aliases:
- Cumulative reactive demand Q1 1-0:5.2.x.255
- Cumulative Reactive Demand Register Q1
keywords:
- 1-0:5.2.x.255
- Cumulative Reactive Demand Register Q1
- cumulative reactive demand Q1
- reactive quadrant Q1
domain_tags:
- cosem_object
- ac_electricity
- reactive_power
- extended_register
- cumulative_demand
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Cumulative Reactive Demand Register import (Q1)

## Definition

Row-level Extended Register object for cumulative reactive demand in quadrant Q1, represented by OBIS `1-0:5.2.x.255`.

## Aliases

- Cumulative reactive demand Q1 1-0:5.2.x.255
- Cumulative Reactive Demand Register Q1

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `reactive_power`
- `extended_register`
- `cumulative_demand`

## Relations

- `instance_of` -> `KB-L3-IC-4-EXTENDED-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:5.2.x.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 aggregate channel",
    "C": "5 reactive quadrant Q1",
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
      "section": "Table 14 AC electricity D codes; C=5, D=2 cumulative maximum"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Cumulative Reactive Demand Register import (Q1) at 1-0:5.2.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row for cumulative reactive quadrant Q1 demand requirements using Extended Register semantics.",
    "Extended Register adds capture_time and status around the cumulative demand value."
  ]
}
```

## Notes

