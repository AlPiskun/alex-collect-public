Alex Collect card pipeline

This folder contains the card scan/listing pipeline and its Windows launcher.
The pipeline can create manual-import CSVs without any plugins. Optional
plugins may add declared actions that the pipeline can invoke after the user
selects the relevant workflow. See ../../docs/PLUGIN-API.md.

User scans and generated output belong in the configured folders, not in the
source repository.
