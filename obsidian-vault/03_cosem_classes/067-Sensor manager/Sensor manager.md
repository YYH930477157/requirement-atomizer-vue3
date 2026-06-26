---
id: KB-L3-IC-67-SENSOR-MANAGER
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Sensor manager
aliases:
- class 67
- CL 67
keywords:
- sensor manager
- class 67
- cl 67
- serial_number
- metrological_identification
- output_type
- raw_value
- processed_value
- sealing_method
domain_tags:
- cosem_class
- sensor
- monitoring
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Sensor manager

## Definition

COSEM interface class (class_id = 67, version = 0) for managing detailed information related to a sensor (mainly non-electricity metering). Combines nameplate/site data, an Extended-register function for raw values, and Register-monitor functions for raw and processed values. Cardinality 0...n.

## Aliases

- class 67
- CL 67

## Domain Tags

- `cosem_class`
- `sensor`
- `monitoring`

## Access Semantics

logical_name is read-only for all clients. All other attributes are **dynamic** (dyn.) — they reflect sensor runtime state and configuration. The nameplate/site attributes (serial_number, metrological_identification, output_type, adjustment_method, sealing_method) and raw/processed value monitor thresholds/actions are read-write (RW) via SET by an authorised management client where configurable; runtime values (raw_value, status, capture_time, processed_value) are read-only (R). Not all modules are necessarily present; unused attributes may be unimplemented.

## Behavior Notes

- Sensor manager manages complex sensor information, mainly for non-electricity metering (MID scope). No OBIS codes defined. Cardinality 0...n.
- **Nameplate/site data** (attr 2-6): serial_number, metrological_identification, output_type (enum), adjustment_method, sealing_method (enum).
- **Extended register for raw value** (attr 7-10): raw_value (CHOICE), scaler_unit (structure), status (CHOICE), capture_time (date-time). Raw data (e.g. pressure sensor voltage) may not have its own OBIS code, hence included here.
- **Register monitor for raw value** (attr 11-12): raw_value_thresholds (array), raw_value_actions (array).
- **Register monitor for processed value** (attr 13-15): processed_value (processed_value_definition), processed_value_thresholds (array), processed_value_actions (array).
- Not all modules necessarily present; unused attributes may be unimplemented or inaccessible.

## Methods

- **reset** (method 1): reset the sensor manager (param: data). Optional.

## Structured Data

```json metadata
{
  "class_id": 67,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "serial_number", "type": "octet-string", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x08"},
    {"attribute_id": 3, "name": "metrological_identification", "type": "octet-string", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x10"},
    {"attribute_id": 4, "name": "output_type", "type": "enum", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x18"},
    {"attribute_id": 5, "name": "adjustment_method", "type": "octet-string", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x20"},
    {"attribute_id": 6, "name": "sealing_method", "type": "enum", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x28"},
    {"attribute_id": 7, "name": "raw_value", "type": "CHOICE", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x30"},
    {"attribute_id": 8, "name": "scaler_unit", "type": "structure", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x38"},
    {"attribute_id": 9, "name": "status", "type": "CHOICE", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x40"},
    {"attribute_id": 10, "name": "capture_time", "type": "date-time", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x48"},
    {"attribute_id": 11, "name": "raw_value_thresholds", "type": "array", "dynamic": true, "mandatory": true, "access_rights": "RW", "short_name": "0x50"},
    {"attribute_id": 12, "name": "raw_value_actions", "type": "array", "dynamic": true, "mandatory": true, "access_rights": "RW", "short_name": "0x58"},
    {"attribute_id": 13, "name": "processed_value", "type": "processed_value_definition", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x60"},
    {"attribute_id": 14, "name": "processed_value_thresholds", "type": "array", "dynamic": true, "mandatory": true, "access_rights": "RW", "short_name": "0x68"},
    {"attribute_id": 15, "name": "processed_value_actions", "type": "array", "dynamic": true, "mandatory": true, "access_rights": "RW", "short_name": "0x70"}
  ],
  "methods": [
    {"method_id": 1, "name": "reset", "parameter_type": "data", "mandatory": false, "short_name": "0x80", "meaning": "Reset the sensor manager."}
  ],
  "access_semantics": [
    "logical_name read-only for all; all other attributes dynamic.",
    "Nameplate/site data (attr 2-6) and runtime values (raw_value, status, capture_time, processed_value) are read-only (R).",
    "Monitor thresholds/actions (attr 11-12, 14-15) are RW via SET by management client where configurable.",
    "Not all modules necessarily present; unused attributes may be unimplemented."
  ],
  "behavior_notes": [
    "Sensor manager manages complex sensor information, mainly for non-electricity metering (MID). No OBIS codes. Cardinality 0...n.",
    "Nameplate/site data: serial_number, metrological_identification, output_type, adjustment_method, sealing_method.",
    "Extended register for raw value (attr 7-10): raw data without own OBIS code included here.",
    "Register monitor for raw value (attr 11-12) and processed value (attr 13-15).",
    "Not all modules necessarily present."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.5.11 Sensor manager (class_id = 67, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.5.11. Full 15 attributes with access_rights, reset method, module structure, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.5.11 (page 202-203).
- Mainly for non-electricity metering (MID scope). No OBIS codes defined.
