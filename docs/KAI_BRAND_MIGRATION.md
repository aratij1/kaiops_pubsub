# KaiMS brand migration

The canonical user-facing identity is **KaiMS**, categorized as **Autonomous
Operations Intelligence**, with the positioning **Understand. Decide. Resolve.**
Brand metadata is centralized in `frontend/react/src/config/brand.ts`.

| Legacy usage | Classification | Treatment |
|---|---|---|
| KaiOps/KAIops in visible UI | USER_VISIBLE_RENAME | Render as KaiMS |
| Service names, image names, topics and environment keys | INTERNAL_KEEP | Preserve for API and deployment compatibility |
| Package/repository names | MIGRATE_LATER | Change only through a separately versioned migration |
| Datamatics-dominant theme assets | REMOVE | No longer imported; keep temporarily for rollback |

Rollback is limited to restoring the old UI imports and metadata. No backend
identifier or historical record is renamed by this milestone.
