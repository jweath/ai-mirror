# Deployment, operation, and recovery

## Deployment

The service uses the repository Dockerfile and a persistent volume mounted at `/data`. Set `MIRROR_DB_PATH=/data/mirror.db`, `MIRROR_ASSET_ROOT=/app`, `PORT=8000`, and a randomly generated `MIRROR_ADMIN_TOKEN` of at least 32 characters. Use one replica and one Uvicorn worker. Set the service health check to `/healthz` with a 60-second timeout and restart policy `ON_FAILURE` with three retries.

These settings are configured directly on the AI Mirror service; [config/railway-settings.json](../config/railway-settings.json) records the reference values but is not auto-applied. The repository intentionally avoids deprecated `railway.toml` Config as Code. Do not apply a whole-project infrastructure specification to the shared instOS project just to deploy this one service. [Railway's current infrastructure guidance](https://docs.railway.com/infrastructure-as-code) explains the migration and named partials if this service later gains an IaC definition.

The initial deployment is a separate `ai-mirror` service inside the existing instOS Railway project. It has its own volume; it does not use the Participation database or worker. Sending begins disabled, with no real roster loaded. The public site/download needs no Slack credentials. The instructor page requires its token.

Use a repository build or an explicit `railway up` upload. The Docker context excludes `.local`, environment files, private course files, databases, Operator memory, and scratch work. Before a release, run tests and lint; never upload an alternate directory containing secrets.

## Slack connection

Create an AI Mirror app in the **current course workspace**. Generate its manifest for the deployed URL:

```sh
ai-mirror slack-manifest --url https://ai-mirror-production-9c9f.up.railway.app
```

The example manifest is in [config/slack-manifest.json](../config/slack-manifest.json). It uses `commands`, `chat:write`, channel metadata scopes, and public/private channel history scopes for message events. It does not request profile/email, file, or DM-history access. Invite the bot only to the project channels it needs. Slack still sends channel events to the app; the handler discards everything outside registered owners' known prompt threads.

Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` on the AI Mirror service. Do not reuse the existing attendance bot token: that app has different scopes and responsibilities. Configure `/slack/events` for events and `/slack/commands` for `/mirror`. Slack URL verification is signed and requires the signing secret; you may need to create the app, set the secret, then finish event URL verification. Reinstall after adding scopes if Slack requires it.

The app checks Slack's HMAC signature using the raw body and a five-minute timestamp window. Repeated message events update the same entry. Repeated slash requests return a private receipt instead of another public entry. Neither signature verification nor a valid workspace is sufficient on its own: student IDs, project channel IDs, and prompt thread IDs are also checked.

## Roster and schedule

Copy the fictional config into a private file (for example `.local/course.json`), replace every example identity, and validate it:

```sh
ai-mirror validate-course .local/course.json
ai-mirror preview .local/course.json
```

Each meeting is explicit:

```json
{"id": "s3-class-01", "at": "2026-10-15T14:35:00-04:00", "kind": "exit_ticket"}
```

**That timestamp is an example, not a confirmed class time.** Use the actual end-of-class time. After daylight saving time changes, use the correct offset. Add `peer_review` dates separately. No schedule is inferred from “Tuesday/Thursday” or an old course page.

Import as inactive, inspect the preview, verify ownership, and activate with a current `activated_at`. Activation checks workspace identity and that the bot belongs to each active channel. Then set `MIRROR_SEND_ENABLED=true`. Never activate fictional example IDs. Identity changes after records exist require deliberate data migration, preventing old entries or queued messages from silently moving to another person or project.

## GitHub and optional model access

For public repositories, unauthenticated GitHub reads work within GitHub's limits. For private repositories, use a fine-grained token with read-only Contents and Issues permissions on exactly the registered repositories. Store it as `GITHUB_TOKEN`. Set `github_enabled` in the course configuration. A service token cannot automatically see repositories owned by students unless access has been granted. Missing access is shown as a collection gap. Closed submission issues authored by the registered GitHub account are discovered automatically when their exact title follows the student-ID/name and sprint convention; the linked human file must be named `reflection.md`. Student-authored revision comments are inspected. An open issue is not a submitted journal.

Set `MIRROR_DIGEST_PROVIDER=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` only when you want model-generated instructor drafts. Choose a model supporting the Responses API and strict structured outputs. Otherwise leave `extractive`, which requires no model account. Selected instructor evidence, including private notes, goes to that provider in OpenAI mode; see [privacy](privacy.md). Provider failures do not queue feedback. Automatic digest attempts are limited to once an hour per class meeting after a failure.

## Receipts, holds, and ambiguous sends

`pending` means waiting for due time and send gates. `delivering` means the database claim was committed before calling Slack. `sent` requires a Slack timestamp. `failed` means Slack explicitly rejected the request. `uncertain` means it may have arrived (timeout, malformed receipt, or process interruption). A new process converts abandoned `delivering` rows to `uncertain`.

Use **Hold all sends** before recovery. An in-flight call can still complete; inspect its receipt. The authenticated API supports:

- `POST /api/hold` — persistent stop for new sends.
- `POST /api/outbox/{delivery-id}/reconcile` — `cancel`, `mark_sent` with the actual `provider_ts`, or `retry_confirmed_unsent`, each with a written reason.
- `POST /api/release-hold` — body `{"action":"release_hold","reason":"..."}`; refused while uncertain/in-flight records remain.

Before `mark_sent` or `retry_confirmed_unsent`, inspect the destination Slack channel and time window. `mark_sent` restores the prompt-thread mapping for a delivered exit prompt. Reconciliation is an operator attestation and audit record; the application does not independently prove absence from Slack. Never retry automatically based only on an empty local receipt.

Prompts older than 15 minutes expire instead of creating a late flood. Feedback remains queued until sent/cancelled or aged out. If a pending message needs different text, cancel it and prepare a new reviewed digest rather than silently changing its payload.

## Backups and retention

Use a consistent SQLite backup:

```sh
ai-mirror backup /private/backup-location/mirror-2026-10-15.db
```

This command operates on `MIRROR_DB_PATH` on the host where it runs. On Railway, use a service shell or a private volume backup; do not assume the local laptop database is production. Keep backups private and apply an appropriate expiry. The initial deployment does not itself establish an ongoing backup policy—configure Railway volume backups before live use.

Restore only with the service stopped and to a fresh database path:

```sh
ai-mirror restore /private/backup-location/mirror-2026-10-15.db /private/new-location/mirror.db
```

Restore sets a persistent send hold and quarantines copied pending/in-flight messages as uncertain. Reconcile Slack's actual history before release. If restoring through a platform snapshot, keep the service stopped or global sending disabled, set `delivery_hold` in the restored database, and reconcile before starting any sender.

The default retention window is 90 days. Current learning entries, evidence snapshots, and private digests age out. Delivery ID/hash tombstones remain; message content is removed after sent/cancelled/expired records age out. Uncertain deliveries need reconciliation and retain their payload until resolved. Roster metadata stays until the course database is retired. Backups have separate retention.

## API for instOS

All `/api/*` routes require `Authorization: Bearer <instructor token>`. No token belongs in a URL. Supported routes cover status, course import, preview, entries, GitHub collection, digest generation/retrieval, feedback approval, and recovery. The browser uses the same API. Instructor credentials are deliberately separate from the attendance service.

The current API is for one instructor/course deployment, not an institutional multi-tenant service. Add per-user authorization and shared database leases before expanding that boundary.
