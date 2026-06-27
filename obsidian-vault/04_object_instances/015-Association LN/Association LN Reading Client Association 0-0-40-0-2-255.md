---
id: KB-OBIS-0-0-40-0-2-255-ASSOCIATION-LN-READING-CLIENT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Association LN - reading client association
aliases:
- Association LN 0-0:40.0.2.255
- Reading client association
keywords:
- 0-0:40.0.2.255
- Association LN reading client
- reading client association
- meter reading association object_list
domain_tags:
- cosem_object
- association
- security_policy
relations:
- relation: instance_of
  target: KB-L3-IC-15-ASSOCIATION-LN
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Association LN - reading client association

## Definition

Row-level COSEM object instance for the reading client Association LN logical name `0-0:40.0.2.255`, used to describe the logical-name association exposed for meter-reading access.

## Aliases

- Association LN 0-0:40.0.2.255
- Reading client association

## Domain Tags

- `cosem_object`
- `association`
- `security_policy`

## Relations

- `instance_of` -> `KB-L3-IC-15-ASSOCIATION-LN`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:40.0.2.255",
  "likely_interface_class_id": 15,
  "likely_interface_class_name": "Association LN",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "40 Association LN",
    "D": "0 association instance group",
    "E": "2 reading client association",
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
      "section": "4.4.4 Association LN common instances"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements for meter-reading client association access.",
    "This Association LN instance anchors the reading client's object_list and access-right context."
  ]
}
```

## Notes

