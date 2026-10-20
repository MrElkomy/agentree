import { Fragment, type ReactNode } from "react";

// Renders model output as plain React nodes: paragraphs, "- " bullet lists and **bold**.
// No HTML is ever interpreted (model output is untrusted). The whole message takes the
// direction of its main language, so an Arabic reply reads right-to-left (bullets on the
// right) even when a line starts with a Latin word such as a package name.
// A chat bubble can't show tables, so a markdown table becomes one bullet per row
// ("Header: value · Header: value"); headings lose their "#", code fences are dropped.

const BULLET = /^\s*(?:[-*•])\s+/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^[\s|:-]+$/;
const HEADING = /^\s*#{1,6}\s+/;
const RTL_CHAR = /[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]/g;
const LTR_CHAR = /[A-Za-z\u00C0-\u024F]/g;

export function textDirection(text: string): "rtl" | "ltr" {
  const rtl = text.match(RTL_CHAR)?.length ?? 0;
  const ltr = text.match(LTR_CHAR)?.length ?? 0;
  return rtl > ltr ? "rtl" : "ltr";
}

function cells(row: string): string[] {
  return row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

function tableToItems(rows: string[]): string[] {
  const [header, ...body] = rows.filter((r) => !TABLE_RULE.test(r)).map(cells);
  if (!header) return [];
  if (!body.length) return [header.join(" · ")];
  return body.map((row) =>
    row.map((c, i) => (header[i] ? `${header[i]}: ${c}` : c)).filter((c) => c.trim()).join(" · "),
  );
}

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      <Fragment key={i}>{part.replaceAll("**", "")}</Fragment>
    ),
  );
}

export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let items: string[] = [];
  const flush = () => {
    if (!items.length) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="list-disc space-y-1 ps-5">
        {items.map((item, i) => (
          <li key={i}>{inline(item)}</li>
        ))}
      </ul>,
    );
    items = [];
  };
  let table: string[] = [];
  const flushTable = () => {
    if (!table.length) return;
    items.push(...tableToItems(table));
    table = [];
  };
  for (const line of text.split("\n")) {
    if (TABLE_ROW.test(line)) {
      table.push(line);
      continue;
    }
    flushTable();
    if (BULLET.test(line)) {
      items.push(line.replace(BULLET, ""));
      continue;
    }
    flush();
    if (line.trim().startsWith("```")) continue;
    const heading = HEADING.test(line);
    const content = line.replace(HEADING, "");
    if (content.trim()) {
      blocks.push(
        <p key={`p-${blocks.length}`} className="break-words">
          {heading ? <strong>{inline(content)}</strong> : inline(content)}
        </p>,
      );
    }
  }
  flushTable();
  flush();
  return (
    <div dir={textDirection(text)} className="flex flex-col gap-2">
      {blocks}
    </div>
  );
}
