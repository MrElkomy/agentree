"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/components/session";
import { Alert, Button } from "@/components/ui";
import { api, uploadFile, type KnowledgeFile } from "@/lib/api";
import { dateTime } from "@/lib/leads";
import { messageFor, messageForCode } from "@/lib/messages";

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.csv,.xlsx";
const POLL_MS = 3000;

const FAILED: Record<string, string> = {
  no_text: "No text found. Scanned PDFs (images of pages) aren't supported yet.",
  pdf_encrypted: "This PDF is password-protected. Upload a copy without a password.",
  too_many_pages: "This PDF has more than 300 pages. Split it into smaller files.",
  too_complex: "This file took too long to read. Try a smaller or simpler file.",
  interrupted: "Reading was interrupted. Try again.",
  no_rows: "No data rows found. The first row must be the column names, with data below it.",
  too_many_rows: "This table has more than 200,000 rows. Split it into smaller files.",
  too_many_columns: "This table has more than 100 columns. Remove the ones you don't need.",
};

function sizeLabel(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function statusLabel(f: KnowledgeFile): string {
  if (f.status === "processing") return "Reading…";
  if (f.status === "ready") return `${f.entry_count} ${f.entry_count === 1 ? "draft" : "drafts"} created`;
  if (f.status === "stored") {
    const rows = f.table_rows ?? 0;
    return `Ready for the Data Analyst · ${rows.toLocaleString("en")} ${rows === 1 ? "row" : "rows"}, ${f.table_columns.length} columns`;
  }
  return "Couldn't read";
}

/**
 * Upload files whose text becomes draft knowledge entries (Task 17). The backend checks the
 * type from the content, reads files in an isolated process and never runs or renders them.
 */
export function KnowledgeFiles({
  base,
  canDelete,
  onDraftsChanged,
}: {
  base: string;
  canDelete: boolean;
  onDraftsChanged: () => Promise<void>;
}) {
  const { handleError } = useSession();
  const url = base.replace(/\/knowledge$/, "/knowledge-files");
  const [files, setFiles] = useState<KnowledgeFile[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setFiles(await api<KnowledgeFile[]>(url));
    } catch (err) {
      setError(handleError(err));
    }
  }, [url, handleError]);

  useEffect(() => {
    let cancelled = false;
    api<KnowledgeFile[]>(url).then(
      (f) => !cancelled && setFiles(f),
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [url, handleError]);

  // While a file is being read, poll; when it finishes, refresh the entries (new drafts).
  const processing = files?.some((f) => f.status === "processing") ?? false;
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(async () => {
      try {
        const next = await api<KnowledgeFile[]>(url);
        setFiles(next);
        if (!next.some((f) => f.status === "processing")) await onDraftsChanged();
      } catch {
        // transient: the next tick retries
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [processing, url, onDraftsChanged]);

  async function onPick(list: FileList | null) {
    const chosen = Array.from(list ?? []);
    if (!chosen.length) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of chosen) {
        try {
          await uploadFile<KnowledgeFile>(url, file);
        } catch (err) {
          setError(`${file.name}: ${messageFor(err)}`);
        }
      }
      await load();
      await onDraftsChanged();
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  async function act(f: KnowledgeFile, action: "retry" | "delete") {
    setError(null);
    try {
      if (action === "delete") await api(`${url}/${f.id}`, "DELETE");
      else await api(`${url}/${f.id}/retry`, "POST");
      await load();
    } catch (err) {
      setError(handleError(err));
    }
  }

  return (
    <section aria-labelledby="files-heading" className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-6">
      <div className="flex flex-col gap-1">
        <h2 id="files-heading" className="text-lg font-semibold">
          Upload files
        </h2>
        <p className="max-w-prose text-sm text-ink-muted">
          PDF, Word (.docx), TXT or Markdown, up to 10 MB each. Their text becomes draft entries
          you review and publish. CSV and Excel tables (first sheet, first row as column names) are
          kept for the Data Analyst, which can calculate from them.
        </p>
      </div>
      <div>
        <input
          ref={input}
          id="knowledge-upload"
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          onChange={(e) => void onPick(e.target.files)}
        />
        <Button type="button" busy={uploading} onClick={() => input.current?.click()}>
          Choose files
        </Button>
        <label htmlFor="knowledge-upload" className="sr-only">
          Upload files
        </label>
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {files?.length ? (
        <ul className="flex flex-col divide-y divide-line">
          {files.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center justify-between gap-3 py-3" data-testid="knowledge-file">
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate font-semibold" dir="auto">
                  {f.filename}
                </span>
                <span className="text-xs text-ink-muted">
                  {f.kind.toUpperCase()} · {sizeLabel(f.size_bytes)} ·{" "}
                  <time dateTime={f.created_at}>{dateTime.format(new Date(f.created_at))}</time>
                </span>
                <span
                  className={`text-sm ${f.status === "failed" ? "text-danger" : "text-ink-muted"}`}
                  data-testid="knowledge-file-status"
                >
                  {statusLabel(f)}
                  {f.status === "failed" && f.error ? ` — ${FAILED[f.error] ?? messageForCode(f.error)}` : null}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                <a
                  href={`${url}/${f.id}/download`}
                  download
                  className="inline-flex min-h-9 items-center rounded-md px-3 text-sm font-semibold text-brand hover:bg-brand-soft"
                >
                  Download
                </a>
                {f.status === "failed" ? (
                  <Button size="sm" variant="secondary" onClick={() => void act(f, "retry")}>
                    Try again
                  </Button>
                ) : null}
                {canDelete ? (
                  <Button size="sm" variant="danger" onClick={() => void act(f, "delete")}>
                    Delete file
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
