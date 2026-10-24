# Facebook workbook settings

These settings are available in **User Settings → Facebook Marketplace export fields**. The same values can be copied from `app/facebook-feed-settings.example.json` as a starter template.

| Workbook column | Setting | Starter value / source |
|---|---|---|
| `TITLE` | Title template | `{title} Trading Card` |
| `PRICE` | Price template | `{price}` (current live-feed price, rounded down to a whole number) |
| `CONDITION` | Condition | `Used - Good` |
| `DESCRIPTION` | Description template | `Trading Card`, followed by the product URL and the payment/shipping note |
| `CATEGORY` | Category | `Antiques & Collectibles` |
| `id` | Product ID template | `{id}` from the live feed |
| `image_link` | Image URL template | `{image_link}` from the live feed |

Templates can use `{title}`, `{description}`, `{product_url}`, `{price}`, `{id}`, and `{image_link}`. The exact starter description renders as:

```text
Trading Card

View and purchase here: https://store.example/product/example-card/

See the store listing for current payment and shipping details.
```

The example domain above is illustrative; `{product_url}` is filled from each product's live feed entry. For the Jeff Torborg product link you supplied, the description will render as:

```text
Trading Card

View and purchase here: https://store.piskun.ca/product/1971-o-pee-chee-jeff-torborg-314-los-angeles-dodgers/

See the store listing for current payment and shipping details.
```

Save changes in User Settings before running the Facebook feed updater. Generated `facebook_delta_*.xlsx` files are created only for newly detected products. After a successful export, Alex Collect opens the newest workbook, the export folder, and the configured Facebook listing/review URL. The pipeline pauses so you can review or complete that handoff before it moves to CanadianShopper.
