import React from "react";

export type AuditFields = {
  created_at?: number | null;
  updated_at?: number | null;
  created_by?: string | null;
  updated_by?: string | null;
};

function formatTimestamp(ts: number | null | undefined): string | null {
  if (ts == null) return null;
  return new Date(ts * 1000).toLocaleString();
}

function hasAuditData(fields: AuditFields): boolean {
  return (
    fields.created_at != null ||
    fields.updated_at != null ||
    Boolean(fields.created_by) ||
    Boolean(fields.updated_by)
  );
}

type AuditCardProps = {
  label: string;
  at: string | null;
  by: string | null | undefined;
};

function AuditCard({ label, at, by }: AuditCardProps) {
  if (!at && !by) return null;
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50/80 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900/50">
      <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">{label}</div>
      {at && <div className="mt-1 text-sm text-zinc-900 dark:text-zinc-100">{at}</div>}
      {by && (
        <div className="mt-0.5 truncate font-mono text-xs text-zinc-500" title={by}>
          by {by}
        </div>
      )}
    </div>
  );
}

export const AuditMetaCards: React.FC<AuditFields> = (fields) => {
  if (!hasAuditData(fields)) return null;
  const createdAt = formatTimestamp(fields.created_at);
  const updatedAt = formatTimestamp(fields.updated_at);
  return (
    <>
      <AuditCard label="Created" at={createdAt} by={fields.created_by} />
      <AuditCard label="Updated" at={updatedAt} by={fields.updated_by} />
    </>
  );
};
