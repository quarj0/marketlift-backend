# Marketlift Marketplace Search

Marketlift search is deliberately marketplace-specific. It does not try to answer broad semantic questions or infer subjective intent such as "good for gaming". Search understands listing text, listing attributes, location, explicit price language, structured filters, and common typos.

## Public API

Primary endpoint:

```http
GET /api/v1/search/listings/
```

Example:

```text
/api/v1/search/listings/?q=samsun+s21+8gb+under+r%24800
```

The query parser interprets the explicit price constraint and unit specification while keeping `samsun` and `s21` as lexical anchors. PostgreSQL trigram matching can match `samsun` to `samsung`. If no S21 listing contains `8gb`, only the specification token is relaxed; the product anchors and price ceiling remain enforced.

A response includes `interpreted` and `relaxed` so the frontend never has to guess what the backend did.

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

A specification-only query is never relaxed into "show everything". For example, if `8gb` has no matches, Marketlift returns no results rather than silently discarding the entire search.

Relaxation is also rejected when the matching product candidates do not actually expose an attribute in that unit family. `Honda Civic 8gb` therefore returns **no results** even when Honda Civic listings exist; Marketlift does not throw away the meaningless `8gb` token and show Civics. In contrast, `Samsung S21 8gb` may relax `8gb` only when the matching S21 candidates themselves have real GB-based attributes (for example 6 GB or 12 GB RAM/storage).

## Supported free-text interpretation

The parser intentionally supports only explicit marketplace syntax:

- lexical listing terms such as `samsung s21`, `single room knust`, or `honda civic 2020`
- BRL price ceilings: `under r$800`, `below 800`, `até 800`, `abaixo de 800`, `menos de 800`, `<= 800`
- BRL price floors: `over r$800`, `above 800`, `acima de 800`, `mais de 800`, `>= 800`
- price ranges: `between 500 and 800`, `entre 500 e 800`, `de 500 a 800`
- explicit unit specifications such as `8gb`, `128gb`, `1tb`, `500km`, `15in`, `90%`
- common spelling mistakes through PostgreSQL `pg_trgm` for alphabetic terms of four or more characters

It does not map subjective phrases to product features or run an LLM.

## Structured filters

The REST endpoint accepts:

- `category`
- `state` / `state_code`
- `city`
- `district`
- `min_price` / `max_price`
- `condition`
- `seller_type`
- `seller_id`
- `verified_only`
- `date_listed`: `today`, `week`, `month`
- `sort`: `relevant`, `newest`, `price_asc`, `price_desc`
- `page_size`
- `cursor`

Dynamic category fields use allowlisted parameters derived from active `CategoryField(filterable=True)` rows:

```text
attr.brand=samsung
attr.ram_gb=8
attr.year.min=2020
attr.year.max=2024
```

Arbitrary ORM paths or field names are never accepted.

## Storage and indexes

Search data is kept out of the transactional `Listing` row in a dedicated one-to-one `ListingSearchDocument` projection. This keeps ordinary listing reads lean while allowing the search document to grow independently. Each projection stores:

- `search_text`: normalized listing/category/location/attribute text
- `search_tokens`: exact normalized tokens used for model/specification matching
- `search_vector`: stored PostgreSQL `tsvector`
- `updated_at`: projection refresh time

Indexes:

- GIN on `search_vector`
- GIN on `search_tokens`
- `gin_trgm_ops` GIN on `search_text`

`pg_trgm` is enabled by the listing search migration. Existing listings are backfilled in bounded batches rather than loading the whole catalogue into memory, and the GIN indexes are created concurrently to reduce deployment locking. `python manage.py rebuild_listing_search` is also available for explicit repair/rebuilding.

## Provider boundary

Clients never know which engine is in use. Search goes through `marketlift.search.service` and a backend class configured by:

```text
MARKETLIFT_SEARCH_BACKEND=marketlift.search.backends.postgres.PostgresListingSearchBackend
```

If Marketlift later needs OpenSearch, a new backend can implement the same contract without changing REST or GraphQL clients.

## Security and operational limits

Search enforces:

- maximum query length
- maximum page size
- maximum result window
- maximum dynamic-filter count
- allowlisted sorts and date filters
- allowlisted category attribute keys
- numeric validation and bounds
- opaque signed cursors tied to the exact query
- per-IP public search rate limiting (proxy headers are trusted only when explicitly configured)
- PostgreSQL statement timeout for search requests
- no user-provided regex, SQL, or ORM lookup paths

The public REST response uses a short cache policy (`max-age=15`, `stale-while-revalidate=30`). No Redis result cache is added yet; it should be introduced only after metrics show repeated hot-query value.

## GraphQL

`listingSearch` uses the same `SearchService`. The dedicated REST endpoint remains the preferred public marketplace search transport because its GET URL is naturally shareable/cacheable and easier to observe at the HTTP/CDN edge.
