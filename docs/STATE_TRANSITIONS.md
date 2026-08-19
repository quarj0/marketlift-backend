# Domain State Transitions

## Listing

```text
draft -> published -> paused -> published
                   -> sold
                   -> expired
published -> under_review -> published (approved)
                          -> rejected (final admin decision)
published -> removed (final enforcement state)
```

`rejected` and `removed` listings cannot be edited or republished through seller actions.

Listings receive an explicit `expires_at` when published. The expiry job either expires the listing or renews it when seller auto-renew is enabled and the listing remains eligible.

## Moderation

```text
open/review -> approved (final moderation decision)
            -> rejected (final moderation decision)
```

Approved cannot later become rejected and rejected cannot later become approved. Removal is a separate enforcement operation.

## Report

```text
open -> review -> resolved (final)
               -> dismissed (final)
```

## Verification

```text
pending -> review -> verified (final attempt)
                  -> rejected (final attempt)
```

A rejected seller may submit a new verification attempt; the old attempt is never changed to approved.

## Support

```text
open -> review -> resolved -> closed
                ^
customer reply can reopen a resolved ticket
```

## Subscription

Paid subscriptions run through their billing period. Scheduled cancellation keeps benefits until period end; expiry falls back to the Free plan.
