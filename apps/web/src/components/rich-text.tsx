import { Fragment, type ReactNode } from "react";

// Renders model output as plain React nodes: paragraphs, "- " bullet lists and **bold**.
// No HTML is ever interpreted (model output is untrusted). Each block picks its own text
// direction, so Arabic replies read right-to-left and English left-to-right.

const BULLET = /^\s*(?:[-*•])\s+/;

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
  for (const line of text.split("\n")) {
    if (BULLET.test(line)) {
      items.push(line.replace(BULLET, ""));
      continue;
    }
    flush();
    if (line.trim()) {
      blocks.push(
        <p key={`p-${blocks.length}`} dir="auto" className="break-words">
          {inline(line)}
        </p>,
      );
    }
  }
  flush();
  return <div className="flex flex-col gap-2">{blocks}</div>;
}
