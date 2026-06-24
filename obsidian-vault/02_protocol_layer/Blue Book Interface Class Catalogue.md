---
id: KB-BLUE-BOOK-IC-CATALOGUE
kb_id: obsidian_energy_metering
type: cosem_class_catalogue
layer: object_model
name: Blue Book Interface Class Catalogue
aliases:
- COSEM interface class catalogue
- interface class catalogue
- class_id catalogue
keywords:
- interface class catalogue
- cosem class catalogue
- class_id
- compact data
- register table
- status mapping
- push setup
- limiter
- parameter monitor
- sensor manager
- ipv6 setup
- ntp setup
- coap setup
domain_tags:
- blue_book
- cosem_class
- object_model
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Blue Book Interface Class Catalogue

## Definition

The Blue Book Part 2 interface class catalogue groups COSEM interface classes by purpose, including measurement data, access control, time and event control, payment, communication profile setup, Internet setup, PLC setup, ZigBee, Wi-SUN, and relation to OBIS objects.

## Aliases

- COSEM interface class catalogue
- interface class catalogue
- class_id catalogue

## Domain Tags

- `blue_book`
- `cosem_class`
- `object_model`

## Structured Data

```json metadata
{
  "coverage_seed_classes": [
    {"class_id": 1, "name": "Data"},
    {"class_id": 3, "name": "Register"},
    {"class_id": 4, "name": "Extended register"},
    {"class_id": 5, "name": "Demand register"},
    {"class_id": 6, "name": "Register activation"},
    {"class_id": 7, "name": "Profile generic"},
    {"class_id": 26, "name": "Utility tables"},
    {"class_id": 61, "name": "Register table"},
    {"class_id": 62, "name": "Compact data"},
    {"class_id": 63, "name": "Status mapping"},
    {"class_id": 40, "name": "Push setup"},
    {"class_id": 48, "name": "IPv6 setup"},
    {"class_id": 65, "name": "Parameter monitor"},
    {"class_id": 66, "name": "Measurement data monitoring objects"},
    {"class_id": 67, "name": "Sensor manager"},
    {"class_id": 71, "name": "Limiter"}
  ]
}
```

## Notes

