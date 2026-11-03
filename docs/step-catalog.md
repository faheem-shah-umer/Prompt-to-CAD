# FreeCAD STEP catalog

Prompt to CAD looks for the local schema version 1 database at `.local/freecad-step-catalog/catalog.sqlite3` and its assets under the adjacent `parts/` folder. Keep the database and assets together. The app reads them without writing to either. Start a new turn after replacing or repairing the catalog.

Ask chat to look up an existing part, for example “Search the STEP catalog for a shaft coupling and tell me what matches.” The agent can search keywords and filter by exact category using `cad_catalog`. For a suitable result it inspects the entry and can use `cad_catalog_insert` to place it in the design. You can specify a world translation in millimetres and rotation in degrees. The insertion preserves the current design and any imported assembly hierarchy.

Catalog metadata and attribution come from the local source. Names and descriptions may be incomplete. Use geometry inspection and measurement to confirm functional dimensions and fit. Imported STEP bodies support the app’s direct geometry operations and contain no FreeCAD feature history. Native revisions retain the imported geometry and its source record, including the catalog fingerprint and original STEP hash.

The project’s [turn log](turn-logs.md) records discovery, tool listing, searches, inspected entries, and insertion outcomes. If the catalog is missing, chat can still generate custom geometry and use the standard part generators.
