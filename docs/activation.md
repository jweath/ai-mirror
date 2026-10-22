# One activation checklist

The student file can be used immediately. The shared service is deployed in a safe setup state; real-class messages and collection wait for the following items. Complete them together before the first live run.

## Course project dashboard

The class board lives at `https://jweath.com/entr/5000/2026/fall/`. It uses Slack OpenID Connect and an explicit course roster. Set `MIRROR_DASHBOARD_URL`, `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, and a new random `MIRROR_SESSION_SECRET` of at least 32 characters; register the exact `/auth/callback` URL in the Slack app. Keep bot installation scopes separate from the `openid profile` sign-in request. Never put app secrets or the instructor token in the browser bundle.

Import the real course map as inactive with `github_enabled` and `slack_enabled` enabled. The read-only collectors run independently of messaging activation: GitHub hourly without a token, every 30 minutes with one; Slack history every 10 minutes, with signed events between polls. Invite the existing Mirror bot to the registered channels, set its bot token/signing secret, then verify `/slack/events`. Leave messaging disabled until its separate schedule and rehearsal are approved.

Students on the roster can view the shared board. Only pins marked `shared` are included; private notes, journals, muddy points, and digests are excluded. Instructor sessions can edit pins and collect evidence. Roster removal revokes access on the next request. A temporary `viewer_slack_ids` entry grants class viewing without inventing project ownership. Unknown repository or GitHub identities remain unset and produce visible gaps.

## Required for class messaging automation

1. **Connect the AI Mirror Slack app.** Create/install the app from the generated manifest in the course workspace, set its bot token and signing secret in the `ai-mirror` Railway service, finish event URL verification, and invite it to the project channels. The existing attendance app has different scopes and is not reused. [Connection steps](operations.md#slack-connection).
2. **Verify the student/project map.** Supply each student's name, stable student ID, Slack member ID, GitHub login, project, project channel ID, and repository. Include both owners of the partner project. Classmate membership is not project ownership. Channel descriptions should display owners for humans; the private roster is authoritative.
3. **Configure the confirmed calendar.** Sprint 3 runs October 15–29, 2026; Sprint 4 runs November 3–12. Opening and closing reviews happen on those start/end dates. Sprint 3 and Sprint 4 Build Journals are due November 3 and November 19, respectively. Final presentations are at Demo Day on November 17. The individual Field Guide is due December 1 at 11:59 p.m. Eastern. Use the [assignment calendar](assignment.md#confirmed-calendar). The published class ends at 2:35 p.m. Eastern; enter explicit exit-ticket timestamps with the correct daylight-saving offset. Choose peer-review prompt times and preview them before activation.
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
