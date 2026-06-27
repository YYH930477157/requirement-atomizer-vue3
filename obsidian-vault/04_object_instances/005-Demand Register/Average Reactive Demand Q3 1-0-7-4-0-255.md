---
id: KB-OBIS-1-0-7-4-0-255-AVERAGE-REACTIVE-DEMAND-Q3
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Average Reactive Demand Register import (Q3)
aliases:
- Average reactive demand Q3 1-0:7.4.0.255
- Average demand Q3
keywords:
- 1-0:7.4.0.255
- Average Reactive Demand Register import Q3
- average reactive demand Q3
- average demand Q3
domain_tags:
- cosem_object
- ac_electricity
- reactive_power
- demand_register
relations:
- relation: instance_of
  target: KB-L3-IC-5-DEMAND-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Average Reactive Demand Register import (Q3)

## Definition

Row-level Demand Register object for average reactive demand in quadrant Q3 during the current demand period, represented by OBIS `1-0:7.4.0.255`.

## Aliases

- Average reactive demand Q3 1-0:7.4.0.255
- Average demand Q3

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `reactive_power`
- `demand_register`

## Relations

- `instance_of` -> `KB-L3-IC-5-DEMAND-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:7.4.0.255",
  "likely_interface_class_id": 5,
  "likely_interface_class_name": "Demand Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 aggregate channel",
    "C": "7 reactive quadrant Q3",
    "D": "4 average value for current demand period",
    "E": "0 total",
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
      "section": "Table 14 AC electricity D codes; D=4 average value"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Average Reactive Demand Register import (Q3) at 1-0:7.4.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row for quadrant-Q3 average reactive demand requirements.",
    "The Demand Register period and number_of_periods attributes determine demand interval behavior."
  ]
}
```

## Notes

