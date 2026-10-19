"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Alert, Button, TextField } from "@/components/ui";
import { api, type Business } from "@/lib/api";
import { slugProblem, slugify } from "@/lib/messages";

export function CreateBusinessForm({ onCancel }: { onCancel?: () => void }) {
  const router = useRouter();
  const { handleError, refreshBusinesses } = useSession();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problem = slugProblem(slug);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (problem || !slug) return;
    setBusy(true);
    try {
      const created = await api<Business>("/api/businesses", "POST", { name: name.trim(), slug });
      await refreshBusinesses();
      router.push(`/b/${created.id}`);
    } catch (err) {
      setError(handleError(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" aria-label="Create a business">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <TextField
        label="Business name"
        name="business-name"
        required
        maxLength={200}
        autoComplete="organization"
        value={name}
        onChange={(e) => {
          setName(e.target.value);
          if (!slugEdited) setSlug(slugify(e.target.value));
        }}
      />
      <TextField
        label="URL name"
        name="business-slug"
        required
        minLength={3}
        maxLength={63}
        spellCheck={false}
        autoCapitalize="none"
        value={slug}
        onChange={(e) => {
          setSlugEdited(true);
          setSlug(e.target.value.toLowerCase());
        }}
        hint="3–63 lowercase letters, digits or hyphens. Used in your public page address."
        error={problem}
      />
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        {onCancel ? (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
        <Button type="submit" busy={busy} disabled={!name.trim() || !slug || Boolean(problem)}>
          Create business
        </Button>
      </div>
    </form>
  );
}
