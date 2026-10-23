# Connect project repositories

The dashboard can read public repositories without credentials. A GitHub 404 can mean a private repository, an old link, or no access; do not treat it as evidence that a student has no project. Confirm the current link with each owner first. Projects built without GitHub can keep their product and Slack links without adding a new repository requirement.

For repositories belonging to different students, use a **GitHub App**. Each fine-grained personal access token is limited to one resource owner; one token cannot cover unrelated student accounts. Do not give the service an instructor's broad personal token. The service supports short-lived installation tokens for each registered repository and stores them only in process memory.

## Register once

1. Open GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
2. Choose a unique name, such as **ENTR AI Mirror — jweath**, and set the homepage to `https://jweath.com/entr/5000/2026/fall/`.
3. Leave user OAuth authorization and device flow off. No user callback is needed for server-to-server collection.
4. Turn off **Active** under Webhook. Collection uses the existing scheduled poll.
5. Repository permissions: **Contents: Read-only**, **Issues: Read-only**. Metadata read access is included automatically. Leave other repository, account, and organization permissions at No access.
6. Choose **Any account** so students can install it on their own accounts. This makes the installation available; it does not grant access to anyone's repositories.
7. Create the app. Record its **App ID**, which is different from its Client ID. Generate and privately retain a PEM private key.

Save the App ID as `GITHUB_APP_ID` and the complete multiline PEM as `GITHUB_APP_PRIVATE_KEY` in Railway's **ai-mirror** service. Never paste the PEM into chat or commit it. Keep the recovery copy in a password manager. Redeploy the service after saving the variables. A legacy single-owner `GITHUB_TOKEN` is unnecessary for the App path.

## Each project owner installs

Send the app's verified installation link to the repository owner. They select **Only select repositories**, choose their class project repository, review the read-only permissions, and install. They do not need to make their repository public or share a personal token. An organization-owned repository may require an organization administrator's approval.

The course's private configuration must contain the current `owner/repository` and each student's actual GitHub login. Installation does not infer which student owns a project. The service looks up the installation automatically and requests a token restricted to that single registered repository with read-only Contents and Issues permissions. It does not need an OAuth Client Secret or student access tokens. Unregistered repositories are rejected before an App request is made.

After installation, use **Collect GitHub** in the signed-in instructor workspace. Verify that the relevant project shows current direct evidence rather than an access gap. Revocation/removal will reappear as a gap. Existing GitHub notification titles in project Slack channels remain labeled **GitHub via Slack**; they are a partial feed, not complete repository history or a substitute for exact journal submissions.

References: [GitHub App registration](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app), [installation authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation), [token limitations](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

## Course workspace setup

The current connection view is `/entr/workspace/#setup` for students and `/entr/instructor/#setup` for the 5000 instructor. Students see only their registered project. The installation link comes from the registered app's authenticated `/app` response, not from a supplied URL.

For first registration, set `GITHUB_APP_BOOTSTRAP_ENABLED=true` and `GITHUB_APP_CONFIG_PATH=/data/github-app.private.json` on the existing service. An authenticated 5000 instructor starts a single-use, hour-limited manifest flow. GitHub generates the credentials; the callback validates the actor/state, permissions and private key, then writes an owner-only, exclusive credential file. The app needs no student OAuth grant to read selected repositories. After registration, disable bootstrap. Complete App ID/private key environment settings take precedence over the recovery file; incomplete settings fail closed.

The webhook is `/entr/workspace/hooks/github`. Verify HMAC-SHA256 on the raw body before parsing; deduplicate deliveries and queue only configured repositories. No webhook updates identity mappings or creates grades. At most two connection probes run per background tick. Periodic evidence collection remains a fallback. The access-log filter removes query strings so registration codes and states do not enter request logs.

Use the published [student setup guide](https://jweath.com/entr/5000/resources/github-setup/). Missing usernames or repositories require an instructor-confirmed mapping, preserving existing course-map history safeguards. An installation alone does not prove a person's account ownership. See [the onboarding roadmap](student-onboarding.md) for the next verified identity step and 5500 document checks.
