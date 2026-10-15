# Data and privacy

The public repository contains code, instructional materials, and fictional examples. Student records, private feedback, roster mappings, database files, API tokens, and local project memory are excluded from Git and the deployment build context.

## What is captured

The service records the registered student's text when they reply to an AI Mirror prompt in their registered project channel, use `/mirror exit`, use `/mirror muddy`, or register a journal link. It ignores unrelated channel conversations and non-owner replies. It records source pointers so the instructor can inspect the original. A shared project has separate student records.

Project-channel reflections and peer feedback are visible to that channel's members. `/mirror muddy` is stored privately for the instructor and acknowledged ephemerally; it is not posted to the channel. The canonical GitHub journal can be private, while the student posts shareable reflection text in Slack for classmates.

When GitHub collection is enabled, the service reads only configured repositories. It collects a rolling 14-day window of commit metadata and issues/PRs updated in that period, with disclosed caps and gaps. It attributes author-account or issue-assignment metadata cautiously. Submitted journal text is fetched from the exact commit. The application does not read all repository code or arbitrary private messages.

## Storage and processing

The instructor service stores learning entries, selected evidence snapshots, private digest drafts, configuration, and delivery records in its private database. The deployed version uses a Railway volume. These records are not a public website or a gradebook. The instructor token gives broad access to this one course; keep it in a password manager and rotate it if exposed. The browser keeps it only in the current tab's memory.

The default extractive digest runs locally in the service process. With explicit `MIRROR_DIGEST_PROVIDER=openai`, the selected evidence—including private notes in the instructor packet—is sent to the configured OpenAI API account to prepare a private draft. Requests use `store: false`; this is not a claim of zero provider retention. Review the account's data policy before enabling this mode. A paid model account is optional.

No model-generated feedback is posted automatically. Human approval names the destination project channel. Private notes may inform the instructor's thinking; they should not be copied into class-visible feedback without the student's permission.

## Retention and corrections

Learning text, evidence snapshots, and digests are retained for the configured period (90 days by default). Delivery identity/hash tombstones remain to prevent duplicate sends; sent/cancelled/expired message content is removed after retention. Uncertain delivery payloads remain until reconciled. Roster metadata remains until the course database is retired. Backups are private and require their own retention schedule. The initial Railway deployment uses daily backups retained for six days, so recently removed records can remain in those snapshots until expiry.

Edits/deletions to captured Slack replies update/remove the current entry when Slack delivers the event. Already-created private digests are historical snapshots and may still contain the earlier text until deleted or aged out. GitHub exact-version submissions intentionally remain historical; later revisions get a new link. Ask the instructor to remove historical copies if a sensitive disclosure needs removal sooner.

Only the instructor has access to service records. Students can use the course's private route to correct a mapping, ask about an entry, or request removal. Do not put customer secrets, credentials, or sensitive personal/team details in shared reflections. Keep private notes concise and relevant to learning support.
