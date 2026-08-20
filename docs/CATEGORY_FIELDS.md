# Category field schema

Marketlift category schemas are platform-managed data. Listing code must not hardcode a provider, brand catalogue, vehicle make list, storage-size list, or similar taxonomy.

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
