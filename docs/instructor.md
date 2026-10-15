# Running AI Mirror in the studio

## Confirmed calendar

Sprint 3 runs October 15–29, 2026; Sprint 4 runs November 3–12. Opening and closing reviews happen on those start/end dates. Sprint 3 and Sprint 4 Build Journals are due November 3 and November 19, respectively. Final presentations are at Demo Day on November 17. The individual Field Guide is due December 1 at 11:59 p.m. Eastern. Journal deadlines follow the existing before-class convention. Reviews are part of the start/end class meetings; they are distinct from the later journal submissions.

## Launch on October 15

Take about 12 minutes in class. Introduce the Build Journal as a new practice starting now, then give students the single [portable file](../skills/ai-mirror/SKILL.md). Explain the division of labor: AI can collect evidence and suggest possibilities; the student's interpretation, goals, learning-check answer, and feedback are gym work. Students link the AI starting material, including suggestions they reject.

Have each student identify an ambitious achievable longer-term goal and one to three sprint priorities. Ask for a small test and a result that would change their decision. Include individually appropriate technical learning: what they will check, understand, or be able to explain. Partners write separately. There is no retrospective catch-up assignment and no blanket ten-test quota.

The file works before the bot is connected. Use manual project-channel posts for an exit ticket and peer exchange during setup. Do not make assistant access or a bot failure a prerequisite for reflection.

## A class meeting

After each Tuesday/Thursday class, a scheduled prompt appears in each registered project channel. Each owner replies in their own words: change, evidence, and muddiest point/next action. The partner channel receives one prompt but expects two individual responses. Optional other-day entries remain optional.

The service records only registered owners' replies to its own prompt threads. `/mirror exit …` is a public fallback; `/mirror muddy …` saves a private instructor note and returns only an ephemeral receipt. Explain this route before collecting sensitive uncertainty. Ordinary conversation is not automatically a journal.

Thirty minutes after a configured class exit-ticket time, the active service prepares a private digest once. You can also collect evidence and generate a digest from the instructor page. Read sources, especially when the summary is missing or ambiguous. Missing captured activity is not evidence of lack of effort. The default extractive mode is intentionally modest; optional AI mode can suggest themes and summaries but remains a draft.

Review or edit the single feedback suggestion for each student. The approval control names the project-channel destination and requires a review checkbox. The approved text enters the delivery queue; the global send flag and course activation still apply. Sensitive private notes must not be copied into that feedback. A send hold can stop new deliveries; it cannot retract an in-flight message.

## Close the muddiest-point loop

Before the next class, read the uncertainties and group two or three useful themes. Keep themes non-identifying; do not quote a private note without the student's permission. Spend a few minutes on an explanation, example, or paired exercise. Ask students to revisit the uncertainty at midpoint or wrap-up: what is clearer, what evidence changed that, and what remains open? An AI answer does not itself establish that the student understands.

## Peer feedback

Add an explicit `peer_review` meeting to the schedule after students have posted their journals. Each student gets one author to review and one incoming reviewer. Partners are never assigned to each other; later rounds avoid previous pairs where feasible. The directed rotation handles odd class sizes.

Students post the human journal text plus the exact commit link in their project channel. Reviewers reply in that thread with a specific strength tied to the goal, an evidence question, and a small next test. Authors reply with what they will use or question and capture that in their journal. Give everyone 60–90 seconds for the capture. If a reviewer is absent or a post is missing, arrange a replacement; do not treat the missing exchange as proof the author failed to engage.

## Submission and assessment

One issue in the student's project repository links their exact journal commit, AI starting material, and peer thread. Closing the issue records submission. Revisions are new commits linked in comments on the same issue. With GitHub collection enabled, the service discovers closed issues titled `Learning journal: <student ID or roster name> — <sprint>` created by that student and reads the linked `reflection.md`. Later student-authored issue comments can point to a revised exact version. The optional `/mirror submit` command registers a receipt immediately when automatic discovery is unavailable. Private code repositories can remain private; shared Slack text gives classmates the reflection without code access.

Use the existing 10-point journal allocation across Sprint 3 and Sprint 4 (5 points each); see the [assignment rubric](assignment.md). Kickoffs and daily notes feed the wrap-up rather than becoming attendance points. Grade specificity, evidence, reasoning, growth, verification, and use of feedback. Honest failure and unresolved questions can earn full credit. Enter only the resulting grades into eLC. The application contains no automatic grade or AI learning score.

## Configuration

Use stable IDs for the workspace, students, project channels, and GitHub repositories. Do not infer ownership from channel membership: the class shares those channels. The authoritative map is the private course configuration. Put a human-readable projection in channel descriptions, for example:

> AI Mirror · ENTR 5000 · Owners: @Alex, @Sam · Repository: owner/project · Individual reflections and goals.

Verify both owners and IDs before activation. Changing descriptions alone does not update the roster. The service does not overwrite channel descriptions automatically.

Upload the private JSON in the instructor page, save it inactive, and preview the exact messages. Each meeting needs an ID, timestamp with UTC offset, and `exit_ticket` or `peer_review` kind. Use real class dates, accounting for holidays and daylight saving time. Use the confirmed calendar above; each timestamp remains explicit so class exceptions and daylight saving time are handled correctly. Activation checks the Slack workspace and bot channel membership; it never backfills old reminders.

When starting Sprint 4, preserve student/project IDs, change `sprint`, replace meetings with confirmed Sprint 4 dates, and use a fresh activation timestamp. Earlier records remain under their original sprint. Keep the longer-term goal and unresolved questions in the student journals. Do not reuse the database for a different course offering.
