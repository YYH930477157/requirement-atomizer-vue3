---
id: KB-L3-IC-66-MEASUREMENT-DATA-MONITORING-OBJECTS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Measurement data monitoring objects
aliases:
- class 66
- CL 66
- waveform capture
keywords:
- measurement data monitoring objects
- class 66
- cl 66
- waveform_data
- trigger_time
- trigger_source
- sampling_rate
- scaler_unit
domain_tags:
- cosem_class
- measurement_data
- control
- waveform
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Measurement data monitoring objects

## Definition

COSEM interface class (class_id = 66, version = 0) for capturing waveform data of a monitored quantity (voltage or current) around a trigger event. One instance holds samples of only one measured quantity at a time. Cardinality 0...n.

## Aliases

- class 66
- CL 66
- waveform capture

## Domain Tags

- `cosem_class`
- `measurement_data`
- `control`
- `waveform`

## Access Semantics

logical_name and the static configuration attributes (sampling_rate, number_of_samples_before/after_trigger, scaler_unit) are read-write (RW) via the SET service by an authorised management client; logical_name is read-only for all. The dynamic attributes (waveform_data, trigger_time, trigger_source, status) are read-only (R) — they reflect runtime capture state. Data capture is only enabled when the before/after window attributes are configured with non-zero values.

## Behavior Notes

- Captures waveform samples of one measured quantity (voltage or current) around a trigger event. One quantity per instance. Cardinality 0...n.
- **waveform_data** (attr 2): dynamic compact-array of sampled values (waveform_element). Capture enabled only when before/after windows (attr 7/8) are non-zero. Candidate for Profile generic capture.
- **trigger_time** (attr 3): dynamic long64-unsigned, microseconds clock — exact trigger execution time. Combined with sample counts gives capture start/end time.
- **trigger_source** (attr 4): dynamic structure {trigger_origin: enum (0 remote, 1 local script), trigger_cause: long-unsigned}.
- **status** (attr 5): dynamic enum, capture status.
- **sampling_rate** (attr 6): static double-long-unsigned, samples per second.
- **number_of_samples_before_trigger** (attr 7): static double-long-unsigned, default 0. Total samples saved = attr7 + attr8.
- **number_of_samples_after_trigger** (attr 8): static double-long-unsigned, default 0.
- **scaler_unit** (attr 9): static structure {scaler, unit} for the waveform quantity.

## Methods

- **reset** (method 1): reset the capture (param: data).
- **trigger** (method 2): initiate a waveform capture; may be manual or driven by a register monitor (param: data).

## Structured Data

```json metadata
{
  "class_id": 66,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "waveform_data", "type": "compact-array", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x08"},
    {"attribute_id": 3, "name": "trigger_time", "type": "long64-unsigned", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x10"},
    {"attribute_id": 4, "name": "trigger_source", "type": "structure", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x18"},
    {"attribute_id": 5, "name": "status", "type": "enum", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x20"},
    {"attribute_id": 6, "name": "sampling_rate", "type": "double-long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x28"},
    {"attribute_id": 7, "name": "number_of_samples_before_trigger", "type": "double-long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "default": 0, "short_name": "0x30"},
    {"attribute_id": 8, "name": "number_of_samples_after_trigger", "type": "double-long-unsigned", "static": true, "mandatory": true, "access_rights": "RW", "default": 0, "short_name": "0x38"},
    {"attribute_id": 9, "name": "scaler_unit", "type": "structure", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x40"}
  ],
  "methods": [
    {"method_id": 1, "name": "reset", "parameter_type": "data", "short_name": "0x48", "meaning": "Reset the waveform capture."},
    {"method_id": 2, "name": "trigger", "parameter_type": "data", "short_name": "0x50", "meaning": "Initiate a waveform capture (manual or register-monitor driven)."}
  ],
  "access_semantics": [
    "logical_name and static config (sampling_rate, before/after sample counts, scaler_unit) are RW via SET by management client; logical_name read-only for all.",
    "Dynamic attributes (waveform_data, trigger_time, trigger_source, status) are read-only (R) — reflect runtime capture state.",
    "Capture only enabled when number_of_samples_before/after_trigger are non-zero."
  ],
  "behavior_notes": [
    "Captures waveform samples of one measured quantity around a trigger event. One quantity per instance. Cardinality 0...n.",
    "waveform_data: dynamic compact-array; total samples = before + after window.",
    "trigger_time: microseconds clock precision for exact capture timing.",
    "trigger_source: {origin remote/local-script, cause}; trigger method manual or register-monitor driven.",
    "waveform_data is a Profile generic capture candidate."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.3.11 Measurement data monitoring objects (class_id = 66, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.3.11. Full attributes with access_rights (dynamic R vs static RW), methods, access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.3.11 (page 101-102).
- One instance holds one measured quantity; separate instances per quantity.
