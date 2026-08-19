# GraphQL Design

## Modularity

`marketlift/graphql/schema.py` is composition only. Each domain owns its API shape:

```text
<domain>/graphql/
├── types.py
├── inputs.py      # when needed
├── mappers.py     # model -> API type mapping
├── queries.py
└── mutations.py
```

Domain business logic belongs in `<domain>/services.py`, not resolvers.

## Query protections

The schema enables:

- Django ORM optimizer
- maximum query depth
- maximum GraphQL token count
- maximum alias count
- request-rate limiting

List/search fields also clamp their own page/limit arguments.

## Listing search

`listingSearch` is the preferred paginated public listing query. It supports:

- free-text query
- category
- state/city/district
- min/max price
- condition
- seller type
- verified sellers only
- date listed
- dynamic category attribute filters
- relevant/newest/price sorting
- promotion-aware relevance

The cursor is opaque to clients. Clients should only pass back the `endCursor` supplied by the server.

## Staff authorization

Admin-only fields use `require_staff()`. Irreversible domain decisions are validated by services/models rather than relying on the admin UI to disable buttons.
