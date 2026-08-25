# Market configuration

Marketlift's marketplace domain is country-neutral. Country availability is now a **database/admin business setting**, not an environment-variable deployment decision.

`MARKETLIFT_MARKET_CODE` remains only a bootstrap and pre-migration fallback. On the first market-catalog migration, that code is enabled and made the default. After that, administrators can enable/disable countries and switch the default market without editing `.env` or restarting the application.

Supported built-in profiles:

| Code | Country | Locale | Currency | Default service-payment provider | Identity label |
| --- | --- | --- | --- | --- | --- |
| BR | Brazil | pt-BR | BRL | Mercado Pago | CPF |
| GH | Ghana | en-GH | GHS | Paystack | Ghana Card |
| NG | Nigeria | en-NG | NGN | Paystack | NIN |
| KE | Kenya | en-KE | KES | Paystack | National ID |
| ZA | South Africa | en-ZA | ZAR | Paystack | South African ID |
| CI | Côte d’Ivoire | fr-CI | XOF | Paystack | National ID |

## Admin-managed settings

The `Market` configuration controls:

- enabled/disabled state;
- default market;
- service-payment provider;
- enabled payment methods (restricted to methods supported by the country profile);
- identity provider identifier;
- display order.

The structural country definition (ISO code, locale, currency, timezone, identity label, location mode) remains code-controlled so an admin cannot accidentally turn Ghana into a BRL/Portuguese market.

The admin GraphQL surface exposes:

- `adminMarkets`
- `updateMarket`
- `adminSellerPlanMarketPrices`
- `setSellerPlanMarketPrice`
- `adminPromotionMarketPrices`
- `setPromotionMarketPrice`

`GET /api/v1/market/` exposes the current default and every enabled market for the marketplace frontend. `GET /api/market/` is retained as a backward-compatible alias.

## Per-market prices

Seller plans and promotion products use explicit market prices. A numeric legacy price is **not** silently reused in another currency.

Example:

- Ghana Professional: GH₵150/month
- Nigeria Professional: ₦18,000/month
- Brazil Professional: R$79/month

A paid plan/promotion without a price for a market is not offered there. `adminMarkets.pricingReady` and `pricingIssues` tell the admin UI what is still missing.

The migration copies existing legacy prices only into the bootstrap/default market. Configure prices for each additional country before launch.

## Secrets stay outside the database

Admin settings choose `paystack`, `mercado_pago`, or `disabled`; secret credentials remain environment/secret-store values:

```env
PAYSTACK_SECRET_KEY=...
PAYSTACK_PUBLIC_KEY=...
MERCADO_PAGO_ACCESS_TOKEN=...
MERCADO_PAGO_WEBHOOK_SECRET=...
```

Buyer-to-seller transactions remain outside Marketlift. Payment adapters only charge sellers for Marketlift plans/promotions.

## Identity verification

Country-specific identity provider selection is admin-managed, but provider credentials remain secrets. Identity numbers continue to be normalized, hashed and masked; plaintext identity values are not persisted.

## Search

The natural-language parser accepts BRL plus common African-market currency forms such as `GH₵6,000`, `₦1.5m`, `KSh 1.8m`, `R 25 000` and `FCFA 500000`. Search and location validation enforce enabled markets from the database catalog.
