# Upload and Media Architecture

Marketlift does not hardcode a cloud provider.

## Storage contract

Domain code knows only an upload asset, logical storage alias, object key and provider-neutral `StorageBackend` interface.

Development defaults to:

```env
MARKETLIFT_STORAGE_BACKEND=uploads.storage.local.LocalStorageBackend
```

A generic bridge is available for any Django-compatible storage implementation:

```env
MARKETLIFT_STORAGE_BACKEND=uploads.storage.django_storage.DjangoStorageBackend
MARKETLIFT_DJANGO_STORAGE_CLASS=<installed backend class>
MARKETLIFT_DJANGO_STORAGE_OPTIONS_JSON={}
```

A future provider-specific adapter may also implement `StorageBackend.prepare_upload()` and return a direct/signed provider upload target. Listings, messaging, verification, reports and support must not be changed when the storage provider changes.

## Lifecycle

```text
PREPARED -> READY -> ATTACHED
     \        \
      -> EXPIRED/DELETED
```

An upload has an owner and purpose. It cannot be attached by another account or reused for another purpose.

Supported purposes include listing images, message images, verification documents/selfies, report evidence, avatars and support attachments.

## Image processing

Strict validation checks the actual image contents. Image uploads can produce WebP variants:

- `thumbnail`
- `card`
- `detail`

Listings and message attachments prefer processed variants when available and fall back to the original.

Production can set:

```env
MARKETLIFT_PROCESS_UPLOADS_ASYNC=true
```

to process variants through Celery.

## Private files

Private objects are authorized through Marketlift before the storage backend is asked for a URL/stream. A deployment adapter serving private remote storage must return expiring/private URLs rather than permanently public object URLs.
