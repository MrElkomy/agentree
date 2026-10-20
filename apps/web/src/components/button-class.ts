// Shared button styles; no client code so server components can use it too.
export type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand text-white hover:bg-brand-hover disabled:bg-brand/50 shadow-[inset_0_-2px_0_rgb(0_0_0/0.18)]",
  secondary:
    "bg-surface text-ink border border-line-strong hover:border-brand hover:text-brand disabled:text-ink-muted",
  ghost: "text-ink-muted hover:text-ink hover:bg-brand-soft disabled:opacity-50",
  danger:
    "bg-surface text-danger border border-danger/40 hover:bg-danger-soft disabled:opacity-50",
};

export function buttonClass(variant: Variant = "primary", size: "md" | "sm" = "md") {
  return [
    "inline-flex items-center justify-center gap-2 rounded-md font-semibold transition-colors",
    "disabled:cursor-not-allowed",
    size === "md" ? "min-h-11 px-4 text-sm" : "min-h-9 px-3 text-sm",
    VARIANTS[variant],
  ].join(" ");
}
