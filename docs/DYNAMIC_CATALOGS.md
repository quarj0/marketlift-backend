# Dynamic product catalogs

Marketlift's listing selectors are cache-first and provider-backed.

## Vehicles

Brazil vehicle fields use FIPE-compatible data on demand:

1. `make` loads the provider's make list.
2. choosing a make loads only that make's models;
3. choosing a model loads only that model's years.

Successful branches are persisted into `CategoryFieldOption` and
`CategoryFieldOptionDependency`, so later requests are local database reads.

The normal application **does not run a full FIPE synchronization**.

If FIPE returns HTTP 429, Marketlift stores a cooldown marker and continues
serving the database cache. `Other / Not listed` remains available because the
dynamic fields allow custom values.

`buses-vans` uses FIPE's truck/microbus collection. Vans that FIPE classifies
under cars/utilities can still be entered through `Other / Not listed`; we do
not merge all passenger cars into the van selector.

## Electronics

The existing curated CSV catalogs remain the first local cache. Wikidata
enriches Brand -> Model branches on demand for:

- phones
- computers/laptops
- tablets
- cameras
- game consoles
- TVs/video
- printers/scanners
- smart watches
- audio equipment
- networking equipment
- other/general electronics

Wikidata is additive and never prunes curated electronics choices.

## Icecat

Icecat's current JSON API retrieves an individual product data sheet by
identifier (GTIN, Icecat ID, or Brand + ProductCode); it is not used as a
Brand -> Model discovery endpoint.

`categories.dynamic_catalogs.lookup_icecat_product` is available for future
specification/originality enrichment once Icecat credentials are configured.

## Bulk commands

`sync_fipe_vehicle_catalog` remains for targeted maintenance/warming but a full
sync is blocked by default. Use `--brand` for a targeted refresh. The
`--allow-full-sync` escape hatch is intentionally explicit.
