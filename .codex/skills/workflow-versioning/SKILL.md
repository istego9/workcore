---
name: workflow-versioning
description: Implement draft/published workflow versioning: publish, rollback, version pinning for runs, and safe migrations. Use when changing version storage, publish/rollback flows, or run version pinning.
---

# Workflow Versioning

## Requirements
- Draft is editable; published versions are immutable.
- Publish creates a new immutable published version.
- Rollback resets draft to the currently active published version.
- Runs reference version_id explicitly (pinned).

## Steps
1) Define the storage model:
   - workflow table + draft blob
   - published_versions table (version_id, hash, created_at, content)
2) Implement publish flow:
   - Validate draft graph and configs
   - Persist new published version
   - Mark as active (if applicable)
3) Implement rollback flow:
   - Replace draft content with active published content
4) Define migration strategy:
   - Prefer additive schema changes
   - If breaking: add migration scripts + compatibility checks

## Definition of done
- Ensure publish/rollback work and are covered by tests.
- Ensure existing runs continue unaffected by draft changes.
- Ensure version content is immutable after publish.
