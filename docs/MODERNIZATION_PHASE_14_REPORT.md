# KaiOps modernization: Phase 14 report

Date: 2026-08-04 (Asia/Calcutta)

## Scope completed

MySQL is now enforced as the only production relational database. The dormant `asyncpg` dependency and PostgreSQL advisory-lock branches were removed. Production configuration rejects non-MySQL URLs; SQLite remains permitted only for local/demo/test isolation. Existing MySQL pooling, schema locking, JSON columns, indexes, pagination caps, migration runner, and archive controls remain in place.

## Files created

- `backend/tests/test_mysql_only_settings.py`
- `docs/MODERNIZATION_PHASE_14_REPORT.md`

## Files modified

- `pyproject.toml`
- `deploy/docker/requirements.service.txt`
- `backend/src/common/common/config.py`
- `backend/src/common/common/database.py`

## Architecture decisions

1. `DB` must be `mysql` and production `DATABASE_URL` must use MySQL.
2. SQLite is a non-production test convenience only.
3. Schema startup locking uses MySQL `GET_LOCK`/`RELEASE_LOCK` exclusively.
4. Existing MySQL migration scripts and metadata indexes remain authoritative.
5. Raw/archive payload extraction will use provider-independent object storage in Phase 15 while MySQL holds searchable metadata.

## Existing functionality preserved

- SQLAlchemy/Pydantic models and async MySQL sessions
- connection pooling, pre-ping, recycling, overflow/timeouts, and circuit breaker
- serialized schema startup and existing MySQL index upgrades
- `scripts/apply-migrations.py`, which already rejects non-MySQL URLs

## Security and operational impact

- hidden PostgreSQL configuration can no longer start
- the production image no longer contains `asyncpg`
- no dual-write path or pgvector dependency exists
- fewer unused drivers reduce dependency and attack surface

## Tests and commands

```text
Repository PostgreSQL runtime scan                 PASS: only negative rejection test remains
docker compose config --quiet                      PASS
Production API-gateway image build                 PASS without asyncpg
MySQL default assertion in rebuilt image           PASS
PostgreSQL URL rejection in rebuilt image          PASS (expected ValidationError)
pip show asyncpg in rebuilt image                   PASS: package not found
```

## MySQL performance baseline

The existing configuration uses `pool_pre_ping`, bounded pool size/overflow/timeouts, and connection recycling. Existing startup migrations create compound audit and incident workflow indexes. New indexes must continue to require measured `EXPLAIN` evidence rather than speculative additions.

## Known limitations

- schema changes are still partly applied during service startup in addition to ordered SQL migrations; these should converge on the migration runner
- retention/archive metadata is completed with the object-storage phase
- full migration tests require the live MySQL integration profile

## Rollback procedure

There is no supported PostgreSQL rollback. If a test needs SQLite, set `ENVIRONMENT=test` and an explicit SQLite URL. Production rollback retains MySQL and reverts only the specific application change under investigation.

## Next phase

Proceed directly to Phase 15 provider-independent object storage and MySQL metadata indexing, removing interactive filesystem archive scans.
