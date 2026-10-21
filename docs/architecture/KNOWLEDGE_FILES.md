# Knowledge file uploads (Task 17)

Owners and members upload files on the **Knowledge** page; their text becomes **draft** entries
that an Owner or Admin reviews and publishes (U-10: manual publish). Code:
`agentree/knowledge/extract.py` (checks and parsing), `files.py` (storage, processing),
`files_api.py` (`/api/businesses/{id}/knowledge-files`), migration 0019.

## What is accepted

| Kind | What happens |
|---|---|
| PDF, DOCX, TXT, MD | Text extracted into titled sections (Markdown and Word headings become titles; long sections split at paragraphs, ≤4,000 characters each, ≤50 per file), saved as drafts linked to the file |
| CSV, XLSX | Stored only, for the Data Analyst (Task 18) |

Limits: 10 MB per file (413 `file_too_large`), 100 files and 200 MB per business
(409 `quota_exceeded`), 30 uploads per user per hour (429 `busy`), PDFs up to 300 pages,
200,000 characters of text per file. Not supported: OCR of scanned PDFs (they fail with
`no_text`), password-protected PDFs (`pdf_encrypted`), URL crawling (needs the SSRF guard).

## Checks (before anything is stored)

- **Type from the content:** `%PDF-` for PDF; a ZIP with `[Content_Types].xml` and
  `word/document.xml` (DOCX) or `xl/workbook.xml` (XLSX); otherwise UTF-8 text without NUL
  bytes. The extension must match what the bytes are (422 `type_mismatch`), e.g. a renamed
  program or a PDF called `.txt`. Other extensions: `unsupported_type`.
- **Archives:** at most 2,000 entries, 100 MB uncompressed and a 200:1 ratio per entry
  (`unsafe_archive`, zip bombs).
- **Names:** displayed names lose any path, control and bidirectional-override characters
  (200 characters at most). Names and contents are never logged or put in the audit trail.

## Processing (isolated)

PDF/DOCX/TXT/MD are read in a **separate process** (`python -m agentree.knowledge.extract`)
with 256 MB of memory, 30 s of CPU, no file writes and a 60 s timeout, one at a time per
server; anything that hits a limit fails as `too_complex` and the API is unaffected. DOCX XML is
parsed with defusedxml (DTDs and entities refused, so billion-laughs/XXE files fail as
`damaged_file`). The upload answers 202 at once (`processing`); the page polls until `ready`
(drafts created), `stored` or `failed` (with a reason). A file stuck in `processing` for 10
minutes (server restart) shows as failed (`interrupted`) and can be retried.

## Safety of the text

Extracted text is untrusted data: drafts are never seen by agents until a person publishes
them, and published text sits inside the knowledge delimiters, which are stripped from entry
content so a file cannot close the block early or pose as instructions. Model markers in a file
gain nothing: the backend validates every marker the model writes.

## Storage and access

`knowledge_files` (metadata) and `knowledge_file_data` (bytes) are tenant-scoped with RLS.
Members list, upload, retry and download; Owners and Admins delete (drafts already created
stay, unlinked). Downloads are always `application/octet-stream` attachments with `nosniff` and
a `sandbox` CSP: files are never executed or rendered by Agentree. Audit:
`knowledge_file.uploaded` / `knowledge_file.deleted` with the kind only.

## Tests

`tests/test_knowledge_files.py`: PDF/DOCX/TXT/MD to drafts, CSV/XLSX stored, splitting,
rejected files (renamed program, PDF as text, HTML, scripts, binary, non-UTF-8, empty, broken
ZIP, zip bomb), oversize, entity-expansion DOCX and scanned PDF fail safely, memory limit and
timeout of the child process, name sanitizing, untrusted text (drafts unused, delimiters cannot
be forged), member/admin permissions, attachment download headers, audit without names, quota,
retry after interruption, tenant isolation; the isolation matrix covers `{file_id}`. E2E: the
upload part of `e2e/sales-agent.spec.ts`.
