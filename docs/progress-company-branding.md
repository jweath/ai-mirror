# Verified company identity in the project tracker

The project tracker keeps its existing roster, progress database, update history,
permissions and original document URLs. Optional company metadata enriches the
display; it is not another store for project progress.

## Private catalog

For a roster at `/data/5500-roster.private.json`, the optional catalog is
`/data/5500-roster.private.companies.json`. Its location is derived from the
configured roster path; no additional environment variable is needed. Keep this
file outside Git and public static assets. For example, using synthetic values:

```json
{
  "schema_version": 1,
  "offering": "entr-5500-fall-2026",
  "companies": [{
    "group_id": "1135-a",
    "name": "Example Company",
    "website_url": "https://example.com/",
    "logo_file": "example-company.png",
    "identity": {"entrepreneur": "Example founder", "company": "Example Company"}
  }]
}
```

Both identity fields must match the current progress record (case-insensitive,
with surrounding whitespace ignored). A later company or entrepreneur change
suppresses stale branding until someone verifies and updates the catalog.
An absent, invalid, oversized or duplicate-containing catalog disables enrichment
without affecting records. Websites must be HTTPS; logo filenames cannot contain
paths. The API returns only the display name, website and logo filename to users
already authorized for that group. It does not return private identity anchors.

Use an empty website/logo when only the company name is verified. Leave unknown
companies out rather than selecting a plausible but unconfirmed company.

## Assets and documents

Verified logos are local assets under `web/progress/company-logos/`. The adjacent
`credits.json` records public company sources and hashes, without student or group
associations. Local delivery avoids third-party image requests from student pages.

Every card and project detail includes a Project document area. Existing native
Google Doc links are labeled Open original Google Doc; other supported documents
are labeled Open original document. Missing links are explicit. This changes
neither the source URL nor its sharing permissions.

## Deployment and rollback

Back up the existing progress database and roster before deployment; compare row
counts and hashes afterward. Add the private catalog atomically, without
overwriting an unexpected existing file. Deploy the tested application with the
same service, volume, authentication and delivery settings. Older application
versions ignore the optional catalog, so an application rollback does not require
reversing a database migration.

Validation covers invalid metadata, stale identity, authorization boundaries,
unchanged progress/history records, and the existing tracker suite. Check cards
and detail pages at desktop and phone widths in both themes, including separate
company/document links and keyboard return focus.
