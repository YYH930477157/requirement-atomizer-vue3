---
id: KB-OBIS-1-0-4-4-0-255-AVERAGE-REACTIVE-DEMAND-EXPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Average Reactive Demand Register export (-A)
aliases:
- Average reactive export demand 1-0:4.4.0.255
- Average demand export -R
keywords:
- 1-0:4.4.0.255
- Average Reactive Demand Register export
- average reactive export demand
- average demand -R
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

# Average Reactive Demand Register export (-A)

## Definition

Row-level Demand Register object for average reactive export demand in the current demand period, represented by OBIS `1-0:4.4.0.255`.

## Aliases

- Average reactive export demand 1-0:4.4.0.255
- Average demand export -R

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
  "obis_pattern": "1-0:4.4.0.255",
  "likely_interface_class_id": 5,
  "likely_interface_class_name": "Demand Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 aggregate channel",
    "C": "4 reactive power- / reactive energy export direction",
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
      "section": "Average Reactive Demand Register export (-A) at 1-0:4.4.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row for average reactive export demand requirements using Demand Register semantics.",
    "The Demand Register period and number_of_periods attributes determine demand interval behavior."
  ]
}
```

## Notes

