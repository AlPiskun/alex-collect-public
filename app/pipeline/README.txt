Alex Collect card pipeline

This folder contains the card scan/listing pipeline and its Windows launcher.
The pipeline can create manual-import CSVs without any plugins. Optional
plugins may add declared actions that the pipeline can invoke after the user
selects the relevant workflow. See ../../docs/PLUGIN-API.md.

Marketplace outputs are separated into:
  facebook_merchant_products/
  woocommerce_products/
  canadianshopper_products/ (including cs-ready staged files)
  ebay_quick_list/

Prior WooCommerce, CanadianShopper, and eBay result batches are consolidated
into history files on the next output run for that marketplace. Details and the
remaining accumulation audit are in OUTPUT-FILES.md. Use Logs & reports in the
GUI to preview and move recognized legacy root files into their folders.

The image workspace remains in output/. User scans and generated output belong
in the configured folders, not in the source repository.
