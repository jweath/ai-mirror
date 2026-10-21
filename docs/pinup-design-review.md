# Project pinup design review

Reviewed against the deployed `https://jweath.com/entr/` and `/entr/5000/` on October 21, 2026, including the rendered page and its computed typography/colors. The source reference is `jweath/entr-site`, commit `04ae70444be5ac0e8df6dba7ad9808f3114305f2`, `src/styles/custom.css`, course navigation, and the bundled font assets.

## Findings and changes

| Finding | Resulting change |
| --- | --- |
| Cream surfaces, green accents, and the Mirror symbol made the pilot read as a separate product. | Use the ENTR wordmark treatment, white/cool-gray surfaces, violet links and selected states, and the same restrained desktop glow. The dashboard remains identified as AI Mirror within ENTR 5000. |
| System fonts did not match the course's typography. | Bundle the same Public Sans body/italic fonts and Familjen Grotesk headings, including their OFL licenses and source manifest. No runtime font service is needed. |
| Cross-service navigation lacked course context. | Add the course's 17rem sidebar, course switch, Fall 2026 links, and violet selected-page marker. Every displayed course destination is a real existing route. On small screens, retain the compact header and ENTR home link. |
| Tiny uppercase field labels and outlined pills gave every detail similar weight. | Use sentence-case labels, larger reading text, quieter source metadata, text links for secondary destinations, and one violet product action. Move the aggregate project count into the footer. |
| The board only had one color scheme. | Add Auto/Light/Dark with the course palette in both schemes, visible keyboard focus, native controls, an accessible editor, and responsive two/one-column layouts. Only the theme choice is stored locally; the access token remains in tab memory. |

## Visual contract

- Body: Public Sans; headings: Familjen Grotesk 600, tracking -0.025em.
- Light: body `#353947`, headings `#202230`, muted text `#555969`, accent `#6957ad`, accent text `#584793`, selected `#ede9f7`, sidebar `#f7f8fb`.
- Dark: body `#d7d8df`, headings `#e9e9ed`, muted `#b8bac7`, accent `#9184d9`, accent text `#d2cefd`, selected `#2b2741`, page `#131522`.
- Navigation uses the deployed names and destinations; it does not imply a shared login across the two services.
- Pin text, source attribution, missing-data qualifications, collection gaps, and the existing access boundary retain their meanings. Color is not used as a grade or project ranking.

The review changes the dashboard preview in the existing draft PR. It does not restyle the course site, alter the course-site PR, or deploy the dashboard.

## Verification

- All 47 service tests pass; both browser scripts pass syntax checks.
- Rendered at the default 1280px viewport and a 390px phone viewport, with no horizontal overflow. The phone filter keeps its full label, and the editor stays inside the viewport.
- Light/dark and Auto theme behavior were inspected; the original viewport and Auto preference were restored after testing.
- Font files are bundled locally and retain the course site's source manifest and OFL licenses.
- Repeated link arrows and duplicated course metadata were removed. Button labels identify their actions; aggregate refresh/count metadata is in the footer.
