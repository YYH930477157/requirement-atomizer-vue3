---
id: KB-L3-IC-20-ACTIVITY-CALENDAR
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Activity Calendar
aliases:
- class 20
- CL 20
keywords:
- class 20
- cl 20
- activity calendar
- calendar_name_active
- season_profile_active
- week_profile_table_active
- day_profile_table_active
- activate_passive_calendar_time
domain_tags:
- cosem_class
- billing_profile
- tariff_calendar
---

# Activity Calendar

## Definition

COSEM class for active and passive tariff calendars, seasons, weeks, and day profiles.

## Aliases

- class 20
- CL 20

## Domain Tags

- `cosem_class`
- `billing_profile`
- `tariff_calendar`

## Structured Data

```json metadata
{
  "class_id": 20,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "calendar_name_active",
      "type": "octet-string",
      "mandatory": true
    },
    {
      "attribute_id": 3,
      "name": "season_profile_active",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 4,
      "name": "week_profile_table_active",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 5,
      "name": "day_profile_table_active",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 6,
      "name": "calendar_name_passive",
      "type": "octet-string",
      "mandatory": true
    },
    {
      "attribute_id": 7,
      "name": "season_profile_passive",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 8,
      "name": "week_profile_table_passive",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 9,
      "name": "day_profile_table_passive",
      "type": "array",
      "mandatory": true
    },
    {
      "attribute_id": 10,
      "name": "activate_passive_calendar_time",
      "type": "date_time",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "activate_passive_calendar"
    }
  ],
  "common_instances": [
    {
      "name": "Activity Calendar",
      "obis": "0-0:13.0.0.255"
    }
  ]
}
```

## Notes

