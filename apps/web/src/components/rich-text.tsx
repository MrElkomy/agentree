import { Fragment, type ReactNode } from "react";

// Renders model output as plain React nodes: paragraphs, "- " bullet lists and **bold**.
// No HTML is ever interpreted (model output is untrusted). Each block picks its own text
// direction, so Arabic replies read right-to-left and English left-to-right.
// A chat bubble can't show tables, so a markdown table becomes one bullet per row
// ("Header: value · Header: value"); headings lose their "#", code fences are dropped.

const BULLET = /^\s*(?:[-*•])\s+/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^[\s|:-]+$/;
const HEADING = /^\s*#{1,6}\s+/;

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
      <ul key={`ul-${blocks.length}`} dir="auto" className="list-disc space-y-1 ps-5">
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
        <p key={`p-${blocks.length}`} dir="auto" className="break-words">
          {heading ? <strong>{inline(content)}</strong> : inline(content)}
        </p>,
      );
    }
  }
  flushTable();
  flush();
  return <div className="flex flex-col gap-2">{blocks}</div>;
}
