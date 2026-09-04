# Category field schema

Marketlift category schemas are platform-managed data. Listing code must not hardcode a provider, brand catalogue, vehicle make list, storage-size list, or similar taxonomy.

Vehicle make/model/year data can be refreshed from a licensed CSV without
changing application code. The required columns are `vehicle_type`, `make`,
`model`, and `year`; supported vehicle types are `cars`, `motorcycles`,
`trucks`, and `buses`. Use
`categories/catalog_templates/vehicle_dataset_example.csv` as the format
reference, validate with `import_vehicle_catalog_dataset <file> --dry-run`,
then run the same command without `--dry-run`. Model-to-year dependencies are
created only from combinations present in the supplied dataset. Marketlift does
not redistribute third-party FIPE data; production operators must use a source
licensed for their commercial use.

For Brazil-specific data, `sync_fipe_vehicle_catalog` refreshes cars,
motorcycles, and trucks from the documented FIPE-compatible API. It supports
an optional `FIPE_API_TOKEN` environment variable and exact repeatable
`--brand` selections for quota-friendly incremental refreshes. Full catalog
refreshes normally require a subscription because the public service has a
daily request allowance. Although FIPE sources can publish a coming model year
early, Marketlift discards years later than the server's current calendar year.

For open-data expansion, `sync_open_vehicle_catalog` imports exact model-year
combinations from the US Department of Transportation NHTSA vPIC service. It
supports cars, motorcycles, trucks, and buses and never imports a year later
than the server's current calendar year. This is an open-data global
alternative; a licensed Brazil-specific dataset remains authoritative for the
local market.

`sync_wikidata_catalogs` appends CC0 Wikidata brand/model choices for phones,
computers, tablets, cameras, consoles, televisions, printers, and smartwatches,
plus dog and cat breeds. These commands import data into Marketlift's database;
the posting form never depends on a third-party API at request time. Always run
with `--dry-run` first and retain “Other / Not listed” because no open catalog
can guarantee every product or lawful pet listing.

## Field input behavior

- `text`, `textarea`, and `number` fields are free-form by nature. Their `options` may be used by clients as suggestions if present.
- `select` fields are strict by default: the submitted value must match a configured option.
- `select` fields with `allowCustomValue: true` are suggestion/combobox fields. Configured options are preferred suggestions, but another non-empty scalar value is accepted.
- For select fields, Marketlift matches configured option values and labels case-insensitively and stores the canonical option value when there is a match. Unknown custom values are preserved only when custom values are enabled.

This allows fields such as phone brand and storage to offer common choices without pretending the platform can know every current or future value.

## Platform-admin GraphQL operations

Administrators with the category-management role can use:

- `createCategory`
- `updateCategory`
- `createCategoryField`
- `updateCategoryField`
- `deleteCategoryField`
- `setCategoryActive`
- `deleteCategory`

Category field create/update accepts the field type, required/filterable flags, custom-choice behavior, validation metadata, sort order, and its option list.

Changing a category field increments the category `schemaVersion`. Field keys and types become immutable after listing values use that field, preserving historical listing meaning. Deleting a field removes it from the current schema while existing listing attributes keep their snapshots.

## Seed defaults

The default phone schema treats `brand` and `storage_gb` as suggested selects with custom values enabled. Other controlled fields such as SIM configuration, network, transmission, fuel type, employment type, and property purpose remain strict selects.
