# Modernization Phase 15 — Indexed Object Archive

## Outcome

Landing-pad history now has a provider-independent object-storage path and a MySQL metadata index. Interactive history APIs query bounded indexed rows; they do not recursively walk archive directories.

## Delivered

- Added S3/MinIO and Azure Blob implementations behind one `ObjectStorage` interface.
- Added `object_storage_metadata` with object identity/URI/type, application/environment, incident and alert relationships, source and timestamps, size, SHA-256 checksum, retention, security classification, processing status, and metadata.
- Added indexed archive listing, controlled streaming download, and signed-access discovery through the monitoring adapter and authenticated API gateway.
- Added checksum verification after upload and deterministic checksum-derived keys.
- Added an idempotent offline migration. It preserves original files, records failures, and is safe to retry.
- Added a dry-run-by-default retention command. `--execute` deletes provider objects first and marks MySQL metadata deleted only after success.
- Corrected the migration default to the repository's actual `backend/ingested_alerts/archive` directory.

## Operations

```text
PYTHONPATH=backend/src/common python scripts/migrate-landing-pad-objects.py --dry-run
PYTHONPATH=backend/src/common python scripts/migrate-landing-pad-objects.py
PYTHONPATH=backend/src/common python scripts/apply-object-retention.py --days 90
PYTHONPATH=backend/src/common python scripts/apply-object-retention.py --days 90 --execute
```

Production writes require `OBJECT_STORAGE_ENABLED=true` and either S3/MinIO or Azure credentials. The migration intentionally never removes the source archive.

## Validation

- Production monitoring image build: passed.
- Python compile of storage, repository, monitoring API, migration, and retention utilities: passed.
- Offline migration dry run against the real archive: 1 discovered, 0 stored, 0 failed.
- Landing-pad partitioning/concurrency regressions: 16 passed.
- Test explicitly fails if the interactive recent endpoint invokes the legacy archive scanner.
- Compose configuration validation: passed.

## Residual operational work

Credentials, bucket/container lifecycle policies, and the first production migration must be provisioned per environment. Azure returns controlled downloads when a delegation SAS is unavailable; S3/MinIO can return short-lived signed URLs.
