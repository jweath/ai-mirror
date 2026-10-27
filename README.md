# AI Mirror

**AI gathers the evidence. Students do the thinking and writing.**

AI Mirror extends the ENTR 5000 Build Journal from Sprint 3 onward. It combines a single portable student skill with a small instructor service for Slack exit tickets, project activity through Slack, peer feedback, and private review.

[Get the student file](https://ai-mirror-production-9c9f.up.railway.app/skill.md) · [Student assignment](docs/assignment.md) · [Instructor guide](docs/instructor.md) · [Morning activation checklist](docs/activation.md)

## For students

Download [`skills/ai-mirror/SKILL.md`](skills/ai-mirror/SKILL.md), attach it to Claude, ChatGPT, or your coding assistant, and say:

> Use AI Mirror to help me start Sprint 3.

That one file contains the complete workflow. No service connection or installation is required. It covers kickoff, short exit tickets, midpoint, wrap-up, a learning question without an AI score, human peer exchange, GitHub submission, presentation preparation, and the individual Field Guide. Chat-only assistants can provide copy/save steps.

The assistant can provide evidence and suggestions first. Students preserve that starting material and write their own reflection, goals, answers, and feedback. There are no retroactive journals or fixed customer-test quotas.

## For the instructor

The [course dashboard](https://jweath.com/entr/5000/2026/fall/) provides source-backed goals, next tests and commitments beside product links and a newest-first timeline of team posts, GitHub notifications from Slack, and project pins. Slack sign-in and an explicit roster protect the class view. John can use the same Slack session for the instructor workspace; the separate operator token remains available for recovery. Private coaching, journals, muddy points, and digests are excluded from the student board.

The [deployed workspace](https://ai-mirror-production-9c9f.up.railway.app/instructor) offers:

- A private roster and explicit schedule, with a preview before activation.
- One Slack exit-ticket thread per project channel per class meeting; each owner replies individually.
- Scoped capture of replies to those prompts; `/mirror muddy` for a private note.
- Slack project activity and GitHub notification titles from all configured team channels, including threaded replies. The current course uses Slack as its activity source; direct repository reads and the custom reader app are retired.
- Deterministic peer assignments that exclude project partners.
- A private 1–2 sentence digest and one feedback suggestion per student. The instructor reviews and edits before queueing feedback to a project channel.
- Durable delivery receipts, send holds, and recovery for uncertain sends.

**Deployment is separate from messaging activation.** Read-only collection can run while class reminders stay disabled. Review the explicit schedule and private instructor rehearsal before enabling sends, following the [activation checklist](docs/activation.md). No student records or credentials are shipped in this repository. The example roster is fictional.

The default digest uses transparent excerpts and prompts without a model API. Optional OpenAI mode produces structured AI summaries and themes after explicit configuration. Neither mode grades students or sends feedback without instructor review.

## Run locally

Python 3.11+; the deployment image uses Python 3.12.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e '.[dev]'
export MIRROR_ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
.venv/bin/uvicorn ai_mirror.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000`. The instructor page requires the token. Sending defaults off. See [.env.example](.env.example) for supported configuration; environment files are not loaded automatically. For a rehearsal, import [the fictional example](config/course.example.json) as inactive. Never activate example identities.

```sh
.venv/bin/ai-mirror validate-course config/course.example.json
.venv/bin/ai-mirror preview config/course.example.json
.venv/bin/ai-mirror peers config/course.example.json --round midpoint
.venv/bin/ai-mirror new --student my-id --sprint sprint-3
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

The CI workflow is provided in [`config/github-actions-ci.yml`](config/github-actions-ci.yml); enabling it requires a GitHub credential with `workflow` scope.

`ai-mirror --help` also covers service configuration, evidence collection, digests, submission issue previews, and database backup/restore. Student submission publishing uses that student's own `gh` login and requires an explicit `--publish` flag.

## Architecture and boundaries

A single FastAPI process serves the site, authenticated instructor API, signed Slack endpoints, and background scheduler. SQLite lives on a persistent volume. Use **one replica and one worker**. Model calls are optional; scheduling does not depend on a student's assistant or laptop being awake.

AI Mirror is an independent service within the instOS Railway project. It does not alter instOS attendance or its native vault. Its explicit learning-data boundary and a future instOS API adapter are described in [architecture](docs/architecture.md). Data handling and retention are in [privacy](docs/privacy.md); deployment and recovery are in [operations](docs/operations.md).

The project feed captures registered owners' shared posts and replies in their configured project rooms, plus titles and links from the official GitHub Slack app for the configured repository. Notification bodies and repository files are excluded. Private reflections, journals, and digests stay outside the class dashboard. The standalone student file remains usable if the service is offline.

## Instructional grounding

This design uses the course's actual daily-summary practices: individualized entrepreneurial/technical goals, small tests with decision thresholds, human verification of AI, goal-based peer feedback, and benefit-first progress reports. UGA's muddiest point, reflective writing, directed paraphrasing, and minute paper inform the reflection and instructor-response loop. [Research and design notes](docs/design.md) link the primary sources and distinguish design choices from observed course practice.

[MIT license](LICENSE). Public code and instructional materials; private student records stay outside Git.

## Shared course workspace

The Fall 2026 [course workspace](docs/course-workspace.md) provides shared Slack sign-in, a private instructor home and the section-scoped 5500 milestone views in the existing service. Source rosters, the static published brief and separate milestone storage preserve record ownership.
