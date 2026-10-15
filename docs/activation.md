# One activation checklist

The student file can be used immediately. The shared service is deployed in a safe setup state; real-class messages and collection wait for the following items. Complete them together before the first live run.

## Required for class automation

1. **Connect the AI Mirror Slack app.** Create/install the app from the generated manifest in the course workspace, set its bot token and signing secret in the `ai-mirror` Railway service, finish event URL verification, and invite it to the project channels. The existing attendance app has different scopes and is not reused. [Connection steps](operations.md#slack-connection).
2. **Verify the student/project map.** Supply each student's name, stable student ID, Slack member ID, GitHub login, project, project channel ID, and repository. Include both owners of the partner project. Classmate membership is not project ownership. Channel descriptions should display owners for humans; the private roster is authoritative.
3. **Set the schedule.** Confirm Sprint 3 end/review, Sprint 4 boundaries, journal deadlines, and remaining presentation/Field Guide dates. Enter the actual Tue/Thu exit-ticket times and peer-review times with timezone offsets; exclude holidays. A separate course-schedule follow-up was requested. No date beyond the October 15 kickoff is assumed here.
4. **Preview and activate.** Import the roster as inactive, inspect each recipient/channel/date/text, then activate and enable `MIRROR_SEND_ENABLED`. Daily volume backups are configured for the initial Railway deployment. Test one explicitly designated rehearsal channel/account before the class-wide activation.

## Optional connections

- **Private GitHub evidence:** supply a fine-grained, read-only token covering the registered repositories, and enable `github_enabled`. This is unnecessary for students to use the file or submit issues themselves. Public repositories can be read without a token within provider limits.
- **AI instructor summaries:** set `MIRROR_DIGEST_PROVIDER=openai`, a service API key, and a supported model. The default extractive digest works without this. Confirm the data handling described in [privacy](privacy.md) before enabling provider processing of instructor evidence.

- **GitHub Actions:** the current GitHub login can publish code but lacks the `workflow` scope. The workflow template is supplied as `config/github-actions-ci.yml`; it has not run on GitHub. After refreshing that permission, copy it to `.github/workflows/ci.yml` and push. Local checks remain available immediately.

## Ready now

- [Student file](https://ai-mirror-production-9c9f.up.railway.app/skill.md), [assignment](assignment.md), [launch guide](instructor.md), and complete GitHub submission instructions.
- [Public landing page](https://ai-mirror-production-9c9f.up.railway.app/) and [private instructor interface](https://ai-mirror-production-9c9f.up.railway.app/instructor).
- Tested workflow and deployable service; no fabricated student mappings or secrets required to distribute the file.

The instructor token is stored privately by the deployment operator and in the service's environment, never in this public document. If it needs replacement, generate a fresh token, set `MIRROR_ADMIN_TOKEN`, redeploy, and keep the new value in a password manager.
