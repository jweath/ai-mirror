# GitHub connection options

Reviewed October 23, 2026. No repository visibility, ownership, or credentials
were changed as part of this comparison.

| Option | Works without a GitHub App? | Consequence for the course |
| --- | --- | --- |
| Public repository | Yes, anonymous API reads | Public contents/history can be read, with 60 API requests/hour per originating IP. Use only where public sharing was already intended; do not publish private journals/interviews to simplify integration. |
| Private repositories in one course organization | Yes, organization member plus selected-repository fine-grained token | One resource owner, read permissions, and explicit repositories. Requires an organization/ownership decision and ongoing token expiry/revocation. A future-course option, not a transparent settings change across current student-owned repos. |
| Read-only deploy keys | Yes | One SSH key per repository, usable for Git files/history. Does not supply the current issues API integration. More operational work across 19 projects. |
| Personal token across student-owned private repositories | Sometimes, with collaborator access and a classic token | A fine-grained token is limited to a single resource owner; GitHub documents collaborator limitations. A classic token is broader and tied to the instructor's account. Not the default for this dashboard. |
| Repository-owned export/workflow | Yes, with a new ingest path | Each repository can push selected evidence using its own workflow credentials. This needs additional workflow/secret/retry setup and changes what evidence the dashboard can independently inspect. Not implemented. |
| Existing GitHub-to-Slack feed | Yes, for partial activity evidence | Already used where available; it does not provide complete journal files, issue conversations, or proof of inactivity. |
| Selected-repository read-only GitHub App | No | Still the recommended fit for the current spread of private student-owned repositories. Repository owners install it once, and can revoke it independently. |

Repository settings can make anonymous reads possible by making a repository
public; there is no private-repository setting that allows anonymous readers.
Keep the existing public reads working while private owners decide how to grant
access. A course organization is the strongest no-App alternative for future
semesters; deploy keys are viable if the evidence scope becomes files only.

Sources:

- [GitHub token types, ownership restrictions, collaborator limitations](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Deploy keys and their repository scope](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [Organization repository roles](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization)
- [Consequences of repository visibility changes](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)
