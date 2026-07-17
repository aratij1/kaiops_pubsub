# Cloud Switch And Data Migration Process

This process enables migration between clouds by switching managed services through profile settings, validating end-to-end behavior, and then migrating existing data.

## 1. Switching service profile

Generate profile overrides:

```powershell
python scripts/switch_service_profile.py --profile azure
```

Supported profiles are in [scripts/profiles/service-profiles.json](../scripts/profiles/service-profiles.json).

The generated file `.env.profile.generated` contains service toggles such as message bus, safety provider, embeddings, evaluation, and observability sink.

## 2. E2E validation after profile switch

Run:

```powershell
./scripts/run_cloud_profile_e2e.ps1 -Profile azure -Rounds 3
```

If Prometheus or Alertmanager are not reachable in the current environment, run partial validation:

```powershell
./scripts/run_cloud_profile_e2e.ps1 -Profile onprem -SkipPipelineCheck -SkipWorkflowRounds
```

This executes:

1. Profile generation
2. Onboarding/safety smoke test
3. Pipeline propagation check
4. Full async incident workflow rounds

## 3. Existing data migration

Run relational migration from old cloud database to new cloud database:

```powershell
python scripts/migrate_existing_data.py \
  --source-url "mysql+pymysql://user:pass@old-host:3306/kaiops" \
  --target-url "mysql+pymysql://user:pass@new-host:3306/kaiops" \
  --truncate-target
```

Dry run first:

```powershell
python scripts/migrate_existing_data.py --source-url "..." --target-url "..." --dry-run
```

Optional table subset:

```powershell
python scripts/migrate_existing_data.py --source-url "..." --target-url "..." --tables incidents,alerts,incident_events
```

## 4. Cutover runbook

1. Freeze writes on source environment.
2. Run final incremental or full migration.
3. Switch deployment profile and secrets in target cloud.
4. Run [scripts/run_cloud_profile_e2e.ps1](../scripts/run_cloud_profile_e2e.ps1) against target.
5. Unfreeze writes and monitor stage completion plus closure event flow.

## 5. Rollback path

1. Re-enable source environment writes.
2. Reset traffic/ingress to source deployment.
3. Re-run smoke plus pipeline verification in source environment.

