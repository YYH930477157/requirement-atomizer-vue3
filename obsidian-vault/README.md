# Energy Metering Knowledge Vault

This Obsidian vault is the source-editing layer for the requirement atomizer knowledge base.

Edit notes here, then compile the vault back to JSON with `python -m requirement_kb.obsidian compile`.

## COSEM Class Families

COSEM interface class notes under `03_cosem_classes/` are grouped by `class_id` using directories such as `003-Register/`.
Keep all versions of the same `class_id` in the same family directory, and distinguish versions in the note filename/frontmatter/metadata.
Row-level OBIS object instances stay under `04_object_instances/` and reference their likely interface class through `likely_interface_class_id`.
