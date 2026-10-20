"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * Disclosure popover: a button that toggles a panel of links/actions.
 * Closes on Escape (returning focus to the button), outside click, and navigation.
 */
export function Popover({
  label,
  button,
  align = "start",
  side = "bottom",
  children,
  buttonClassName = "",
  panelClassName = "",
}: {
  label: string;
  button: ReactNode;
  align?: "start" | "end";
  side?: "top" | "bottom";
  children: (close: () => void) => ReactNode;
  buttonClassName?: string;
  panelClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className={buttonClassName}
      >
        {button}
      </button>
      <div
        id={panelId}
        hidden={!open}
        className={[
          "absolute z-30 min-w-64 rounded-lg border border-line bg-surface p-1.5",
          "shadow-[0_18px_40px_-18px_rgb(18_56_41/0.4)]",
          align === "end" ? "right-0" : "left-0",
          side === "top" ? "bottom-full mb-2" : "top-full mt-2",
          panelClassName,
        ].join(" ")}
      >
        {open ? children(() => setOpen(false)) : null}
      </div>
    </div>
  );
}

export const menuItemClass =
  "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm text-ink hover:bg-brand-soft focus-visible:bg-brand-soft";
