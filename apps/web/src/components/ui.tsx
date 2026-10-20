"use client";

import {
  forwardRef,
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";
import type { Role } from "@/lib/api";
import { ROLE_LABEL } from "@/lib/roles";
import { buttonClass, type Variant } from "./button-class";

export { buttonClass };

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "md" | "sm";
  busy?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", busy = false, className = "", children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={`${buttonClass(variant, size)} ${className}`}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <Spinner /> : null}
      {children}
    </button>
  );
});

export function Spinner({ label }: { label?: string }) {
  return (
    <span
      role={label ? "status" : undefined}
      className="inline-flex items-center gap-2 text-ink-muted"
    >
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent"
      />
      {label ? <span>{label}</span> : null}
    </span>
  );
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: ReactNode;
  error?: string | null;
};

export function TextField({ label, hint, error, id, className = "", ...rest }: FieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={inputId} className="text-sm font-semibold text-ink">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        className={[
          "min-h-11 rounded-md border bg-surface px-3 text-base text-ink",
          "placeholder:text-ink-muted/70 focus-visible:border-brand",
          error ? "border-danger" : "border-line-strong",
        ].join(" ")}
        {...rest}
      />
      {hint ? (
        <p id={hintId} className="text-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-sm font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { label: string; hideLabel?: boolean };

export function SelectField({ label, hideLabel, id, className = "", children, ...rest }: SelectProps) {
  const autoId = useId();
  const selectId = id ?? autoId;
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={selectId} className={hideLabel ? "sr-only" : "text-sm font-semibold text-ink"}>
        {label}
      </label>
      <select
        id={selectId}
        className="min-h-11 rounded-md border border-line-strong bg-surface px-3 text-base text-ink focus-visible:border-brand"
        {...rest}
      >
        {children}
      </select>
    </div>
  );
}

type Tone = "error" | "success" | "warning" | "info";

const TONES: Record<Tone, string> = {
  error: "border-danger/30 bg-danger-soft text-danger",
  success: "border-brand/25 bg-brand-soft text-brand-deep",
  warning: "border-warn/25 bg-warn-soft text-warn",
  info: "border-line bg-surface text-ink",
};

export function Alert({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-md border px-4 py-3 text-sm leading-relaxed ${TONES[tone]}`}
    >
      {children}
    </div>
  );
}

const ROLE_STYLE: Record<Role, string> = {
  owner: "bg-brand text-white",
  admin: "bg-brand-soft text-brand-deep ring-1 ring-brand/30",
  member: "bg-surface text-ink-muted ring-1 ring-line-strong",
};

export function RoleBadge({ role }: { role: Role }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${ROLE_STYLE[role]}`}
    >
      {ROLE_LABEL[role]}
    </span>
  );
}
