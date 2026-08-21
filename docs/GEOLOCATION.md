# Marketlift geospatial location

Marketlift keeps human-readable listing location snapshots (`country_code`, `state`, `state_code`, `city`, `district`) and stores a private PostGIS `PointField` for distance/radius search. Exact listing coordinates are not exposed by the public listing/search serializers.

## Place resolution

The geocoder is an adapter configured by `MARKETLIFT_GEOCODER_BACKEND`. Development defaults to the Nominatim adapter; production defaults to the disabled adapter so a production-appropriate provider/self-hosted endpoint can be selected explicitly.

Public endpoints:

- `GET /api/v1/locations/search/?q=Campinas%2C%20Brazil`
- `GET /api/v1/locations/reverse/?lat=-23.5505&lng=-46.6333`

Both return normalized location data plus a signed `locationToken`. Pass that token to `createListing`/`updateListing`. When a token is supplied, the backend ignores client-supplied location strings/coordinates and uses the signed resolver values.

`MARKETLIFT_REQUIRE_RESOLVED_LISTING_LOCATION` defaults to true in production. This prevents arbitrary frontend strings from becoming canonical production listing locations.

## Radius search

REST is the primary public search API:

`GET /api/v1/search/listings/?q=samsung+s21&lat=-23.5505&lng=-46.6333&radius_km=10&sort=distance`

GraphQL `listingSearch` supports `latitude`, `longitude`, `radiusKm`, and `sort: "distance"` through the same search service. `nearbyListings` is now a true PostGIS radius query rather than same-city filtering.

Coordinate searches use `Cache-Control: private, no-store`; ordinary public searches retain the short shared-cache policy.

## Infrastructure

Django uses `django.contrib.gis.db.backends.postgis`. Local Docker runs PostgreSQL 17 with PostGIS. Managed production PostgreSQL must support the `postgis` extension.

The `0007_listing_geospatial_location` migration enables PostGIS and creates the spatial listing field/index. Existing listings keep `location_point = NULL` until edited/resolved; they remain searchable by their existing textual location, but are excluded from radius searches until they have coordinates.

## Provider contract

Implement `marketlift.location.providers.base.GeocoderBackend` to add another provider. Search/business logic depends only on normalized `LocationCandidate` values and signed resolver tokens, not on Nominatim-specific response objects.
