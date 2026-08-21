# Marketlift Marketplace Search

Marketlift search is marketplace-specific. It searches listing text, category attributes, Brazilian location hierarchy, explicit price language, distance, and common spelling mistakes. It does not infer subjective intent such as "good for gaming".

## Public API

Primary endpoint:

```http
GET /api/v1/search/listings/
```

Example free-text search:

```text
/api/v1/search/listings/?q=samsun+s21+8gb+under+r%24800
```

The query parser interprets explicit price/specification syntax while keeping product terms as lexical anchors. PostgreSQL trigram matching can match common misspellings such as `samsun` to `samsung`. If no otherwise-matching product contains a requested specification, only a valid specification token may be relaxed; product anchors and price constraints remain enforced.

A response includes `interpreted` and `relaxed` so clients do not have to reconstruct backend search decisions.

```json
{
  "query": "samsun s21 8gb under r$800",
  "interpreted": {
    "terms": ["samsun", "s21"],
    "specifications": ["8gb"],
    "maxPrice": 800.0
  },
  "relaxed": [
    {
      "kind": "specification",
      "value": "8gb",
      "reason": "NO_EXACT_MATCHES"
    }
  ],
  "totalCount": 2,
  "nextCursor": "...",
  "results": []
}
```

A specification-only query is never relaxed into "show everything". Relaxation is also rejected when candidate products do not expose an attribute in that unit family. For example, `Honda Civic 8gb` returns no results rather than dropping `8gb` and showing unrelated Civics.

## Supported free-text interpretation

The parser intentionally supports explicit marketplace syntax:

- listing/product/location text such as `samsung s21`, `apartamento pinheiros`, or `honda civic 2020`
- BRL price ceilings: `under r$800`, `below 800`, `até 800`, `abaixo de 800`, `menos de 800`, `<= 800`
- BRL price floors: `over r$800`, `above 800`, `acima de 800`, `mais de 800`, `>= 800`
- price ranges: `between 500 and 800`, `entre 500 e 800`, `de 500 a 800`
- explicit unit specifications such as `8gb`, `128gb`, `1tb`, `500km`, `15in`, `90%`
- common spelling mistakes through PostgreSQL `pg_trgm` for alphabetic terms of four or more characters

It does not map subjective phrases to product features or invoke an LLM.

## Brazilian location reference API

The frontend should use Marketlift's location API instead of shipping its own municipality catalogue or calling IBGE directly from the browser:

```http
GET /api/v1/locations/regions/
GET /api/v1/locations/states/?region=SE
GET /api/v1/locations/cities/?state=SP&q=camp&limit=40
GET /api/v1/locations/neighborhoods/?state=SP&city=São%20Paulo&q=pin
```

- Regions and all 27 federative units are maintained locally by the backend.
- Municipality autocomplete is backed by the official IBGE locality API and server-side caching, with public Marketlift inventory as a fallback.
- Neighborhood autocomplete is derived from public listing inventory for the selected state/city. Neighborhood remains editable because there is no clean authoritative national neighborhood enum.
- Queries are accent-insensitive where the backend performs catalogue filtering.

For coordinate/place resolution, Marketlift also exposes:

```http
GET /api/v1/locations/search/?q=Campinas%2C%20Brazil
GET /api/v1/locations/reverse/?lat=-23.5505&lng=-46.6333
```

Resolver results are Brazil-only and include a signed `locationToken` for listing mutations.

## Structured filters

The listing search endpoint accepts:

- `country_code` / `countryCode` (currently `BR`)
- `region`: `N`, `NE`, `CO`, `SE`, `S`
- `state` / `state_code` / `stateCode`: Brazilian UF code such as `SP`
- `city`
- `district` / `neighborhood` / `neighbourhood`
- `category`
- `min_price` / `max_price`
- `condition`
- `seller_type`
- `seller_id`
- `verified_only`
- `date_listed`: `today`, `week`, `month`
- `latitude` / `lat`
- `longitude` / `lng` / `lon`
- `radius_km` / `radiusKm`
- `sort`: `relevant`, `newest`, `price_asc`, `price_desc`, `distance`
- `page_size`
- `cursor`

Examples:

```text
# Hierarchical location filtering
/api/v1/search/listings/?region=SE&state=SP&city=São%20Paulo&district=Pinheiros

# Product + price + location
/api/v1/search/listings/?q=samsung+galaxy&max_price=9000&state=SP&city=São%20Paulo

# Radius search
/api/v1/search/listings/?q=iphone&lat=-23.5505&lng=-46.6333&radius_km=10&sort=distance
```

Region/state combinations are validated. For example, `region=NE&state=SP` is rejected instead of silently producing confusing results. Radius and distance sorting require valid coordinates.

Dynamic category fields use allowlisted parameters derived from active `CategoryField(filterable=True)` rows:

```text
attr.brand=samsung
attr.ram_gb=8
attr.year.min=2020
attr.year.max=2024
```

Arbitrary ORM paths or field names are never accepted.

## Storage and indexes

Search data is kept out of the transactional `Listing` row in a dedicated one-to-one `ListingSearchDocument` projection. Each projection stores normalized listing/category/location/attribute text and PostgreSQL search structures.

Indexes include:

- GIN on `search_vector`
- GIN on `search_tokens`
- `gin_trgm_ops` GIN on `search_text`
- PostGIS spatial index on listing `location_point`

Existing search documents can be repaired with:

```bash
python manage.py rebuild_listing_search
```

## Provider boundary

Clients never know which search engine is in use. Search goes through `marketlift.search.service` and a backend class configured by:

```text
MARKETLIFT_SEARCH_BACKEND=marketlift.search.backends.postgres.PostgresListingSearchBackend
```

If Marketlift later needs OpenSearch, a new backend can implement the same contract without changing REST or GraphQL clients.

Location resolution follows the same principle through `MARKETLIFT_GEOCODER_BACKEND`; search/listing domain code does not depend on a specific geocoding vendor.

## Security and operational limits

Search enforces maximum query/page/filter sizes, allowlisted sorts and attributes, numeric bounds, opaque signed cursors tied to the exact query, per-IP public rate limiting, PostgreSQL statement timeouts, and no user-provided regex/SQL/ORM lookup paths.

Coordinate searches use private/no-store caching because coordinates can disclose a user's current area. Ordinary public searches retain a short shared-cache policy.

## GraphQL

`listingSearch` uses the same search service and supports the same hierarchy and coordinate fields. `nearbyListings` is a true PostGIS radius query. REST remains the preferred public marketplace search transport because its GET URL is shareable, cacheable, and easier to observe at the HTTP/CDN edge.
