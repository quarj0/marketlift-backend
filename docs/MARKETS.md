# Market profiles

Marketlift's marketplace domain is country-neutral. A deployment selects an active market with `MARKETLIFT_MARKET_CODE`; listing, search, identity, currency and service-payment defaults come from that profile.

Supported profiles in this release:

| Code | Country | Locale | Currency | Default service-payment provider | Identity label |
| --- | --- | --- | --- | --- | --- |
| BR | Brazil | pt-BR | BRL | Mercado Pago | CPF |
| GH | Ghana | en-GH | GHS | Paystack | Ghana Card |
| NG | Nigeria | en-NG | NGN | Paystack | NIN |
| KE | Kenya | en-KE | KES | Paystack | National ID |
| ZA | South Africa | en-ZA | ZAR | Paystack | South African ID |
| CI | Côte d’Ivoire | fr-CI | XOF | Paystack | National ID |

## Ghana deployment

```env
MARKETLIFT_MARKET_CODE=GH
MARKETLIFT_ENABLED_MARKETS=GH
MARKETLIFT_PAYMENT_PROVIDER=paystack
MARKETLIFT_PAYMENT_METHODS=card,mobile_money
PAYSTACK_SECRET_KEY=...
PAYSTACK_PUBLIC_KEY=...
MARKETLIFT_PAYMENTS_ENABLED=true
```

Buyer-to-seller transactions remain outside Marketlift. Paystack/Mercado Pago are only adapters for seller subscriptions, promotions and other fees paid **to Marketlift**.

The frontend can read `GET /api/market/` to discover the active currency, locale, payment methods and identity label rather than hardcoding Brazil.

## Identity verification

Use `MARKETLIFT_IDENTITY_VERIFICATION_ENABLED`; the old `MARKETLIFT_CPF_VERIFICATION_ENABLED` setting remains a Brazil compatibility alias. Identity numbers are hashed and masked; plaintext values are not persisted. Country-specific external verification providers remain pluggable and are intentionally not faked by this refactor.

## Search

The natural-language parser accepts BRL plus common Paystack-market currency forms such as `GH₵6,000`, `₦1.5m`, `KSh 1.8m`, `R 25 000` and `FCFA 500000`. Country/location enforcement is based on the active/enabled market profile.
