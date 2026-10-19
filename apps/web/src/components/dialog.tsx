"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

/**
 * Modal built on the native <dialog> element: focus is moved in and trapped by the
 * browser, Escape closes it, and focus returns to the opener on close.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border border-line bg-surface p-0 text-ink shadow-[0_24px_60px_-20px_rgb(18_56_41/0.45)]"
    >
      <div className="flex flex-col gap-5 p-6">
        <div className="flex flex-col gap-1">
          <h2 id={titleId} className="text-xl font-semibold">
            {title}
          </h2>
          {description ? (
            <p id={descId} className="text-sm text-ink-muted">
              {description}
            </p>
          ) : null}
        </div>
        {open ? children : null}
      </div>
    </dialog>
  );
}
