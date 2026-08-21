# Upload and Media Architecture

Marketlift keeps storage provider details behind a provider-neutral `StorageBackend` contract. Domain apps work with upload assets, logical storage aliases, and object keys; listings, messaging, verification, reports, and support do not import Cloudflare/AWS SDKs.

## Local development

With no remote storage credentials configured, Marketlift continues to use local storage:

```env
MARKETLIFT_STORAGE_BACKEND=uploads.storage.local.LocalStorageBackend
```

A generic bridge also remains available for any Django-compatible storage backend.

## S3-compatible / Cloudflare R2 deployment

When all R2 variables are present, Marketlift automatically routes the four logical stores through the generic S3-compatible adapter:

```env
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_ACCOUNT_ID=...
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com

R2_PUBLIC_BUCKET=marketlift-public
R2_PRIVATE_BUCKET=marketlift-private
R2_EVIDENCE_BUCKET=marketlift-evidence
R2_TEMP_BUCKET=marketlift-temp
R2_REGION=auto
```

`R2_MEDIA_BUCKET` is accepted as a backwards-compatible fallback for `R2_PRIVATE_BUCKET`, but new deployments should use `R2_PRIVATE_BUCKET`.

The logical routing is:

| Purpose | Staging | Final logical store |
| --- | --- | --- |
| listing image | temp | public |
| seller avatar | temp | public |
| message image | temp | private |
| support attachment | temp | private |
| verification document/selfie | temp | evidence |
| report evidence | temp | evidence |

Bucket names and the endpoint are infrastructure configuration only. The same adapter can target another S3-compatible provider without changing domain code.

A custom public asset domain is optional. Until one exists, Django returns short-lived signed object URLs. Later, configure:

```env
R2_PUBLIC_BASE_URL=https://assets.example.com
```

and public assets can resolve to stable CDN URLs without changing database records.

## Direct upload lifecycle

For S3-compatible storage, the browser never receives the R2 access key or secret key.

```text
browser
  -> POST Django prepare endpoint
  <- short-lived signed PUT target for temp bucket
  -> PUT file directly to temp object storage
  -> POST Django complete endpoint
Django
  -> verifies stored size/type/content
  -> promotes validated object to public/private/evidence
  -> generates image variants when applicable
  -> deletes temporary source object
```

The application's session/CSRF credentials are sent only to Django. The browser uses the signed provider request without Django cookies.

Provider CORS must allow the actual marketplace/admin frontend origins for direct signed browser operations. CORS does not make a private bucket public.

## Lifecycle

```text
PREPARED -> READY -> ATTACHED
     \        \
      -> EXPIRED/DELETED
```

An upload has an owner and purpose. It cannot be attached by another account or reused for another purpose. Expired/deleted assets and generated variants are deleted from their actual logical storage backend.

The application expires abandoned prepared uploads, but the temporary bucket should also have a provider lifecycle rule (for example deleting objects after 1-3 days) as defense in depth for interrupted requests or failed cleanup jobs.

## Image processing

Strict validation checks actual file contents instead of trusting extensions. Image uploads can produce WebP variants:

- `thumbnail`
- `card`
- `detail`

Production can set:

```env
MARKETLIFT_PROCESS_UPLOADS_ASYNC=true
```

to process variants through Celery.

Public final objects use immutable cache metadata because their object keys are UUID-based. Private/evidence objects use private/no-store cache metadata.

## Private files

Private/evidence objects are authorized through Marketlift before storage access is granted. Django returns a short-lived signed GET URL after authorization; permanent public object URLs are not used for message attachments, support files, verification evidence, or report evidence.

## Credentials and dependencies

The S3-compatible adapter uses Marketlift's existing HTTP client dependency and AWS Signature V4 directly, so no Cloudflare-specific SDK is required. Do not put object-storage credentials in frontend environment variables or commit them to the repository.
