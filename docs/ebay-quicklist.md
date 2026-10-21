# eBay Quick List settings

Alex Collect's optional Quick List stage is a manual listing aid, not an eBay uploader. After a card-listing run it asks whether you want to prepare any cards; enter specific card numbers, a range, or `all`. It creates a local HTML page with copyable/draggable values and image URLs, then opens each selected card's configured eBay template in a separate tab in the preferred browser. You review and submit the listing on eBay yourself.

## User Settings

- **Ask which cards to prepare** — defaults to on. Turn it off to skip the prompt.
- **Sport template URLs** — Football, Baseball, Hockey, and optional Basketball. If a sport-specific URL is blank, the default template URL is used.
- **Image URL base** — optional override for public WooCommerce uploads. `{year}` and `{month}` are substituted with the current upload year/month. If blank, Alex Collect uses the configured WooCommerce site URL plus `/wp-content/uploads/{year}/{month}`.
- **Default item specifics** — condition, year, manufacturer, card number, player, set, grade, and autographed value. Parsed card data takes precedence where available; these values fill gaps.
- **Fallback description** — used only when the parsed card description is empty.

The Quick List page also shows local image filenames when available. Public image URLs can be dragged/copied, but eBay may require image files to be uploaded through its own form. An eBay account/sign-in or seller setup may be required to submit; the helper does not bypass eBay requirements and does not call eBay APIs.
