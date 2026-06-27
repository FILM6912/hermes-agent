import React, { useMemo } from "react";
import { useLanguage } from "@/hooks/useLanguage";
import type { HermesProfileSummary } from "@/services/hermes/profiles";

export type KanbanAssigneeSelectProps = {
  value: string;
  onChange: (value: string) => void;
  profiles: HermesProfileSummary[];
  /** Board history / CLI lanes not in the profile list. */
  historicalAssignees?: string[];
  className?: string;
  disabled?: boolean;
};

function sortedProfileNames(profiles: HermesProfileSummary[]): string[] {
  const names = profiles.map((p) => p.name).filter(Boolean);
  return [...names].sort((a, b) => {
    if (a === "default") return -1;
    if (b === "default") return 1;
    return a.localeCompare(b, undefined, { sensitivity: "base" });
  });
}

/** Profile dropdown for Kanban assignee (mirrors legacy _kanbanPopulateAssigneeSelect). */
export const KanbanAssigneeSelect: React.FC<KanbanAssigneeSelectProps> = ({
  value,
  onChange,
  profiles,
  historicalAssignees = [],
  className = "",
  disabled = false,
}) => {
  const { t } = useLanguage();
  const { profileNames, extraNames } = useMemo(() => {
    const seen = new Set<string>();
    const profileNames = sortedProfileNames(profiles);
    for (const name of profileNames) seen.add(name);

    const extras: string[] = [];
    for (const name of historicalAssignees) {
      const trimmed = name?.trim();
      if (trimmed && !seen.has(trimmed)) {
        extras.push(trimmed);
        seen.add(trimmed);
      }
    }
    const current = value.trim();
    if (current && !seen.has(current)) {
      extras.push(current);
    }
    return { profileNames, extraNames: extras };
  }, [profiles, historicalAssignees, value]);

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={className}
    >
      {profileNames.length > 0 && (
        <optgroup label={t("kanban.assigneeProfiles")}>
          {profileNames.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </optgroup>
      )}
      {extraNames.length > 0 && (
        <optgroup label={t("kanban.assigneeOther")}>
          {extraNames.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </optgroup>
      )}
      <option value="">{t("kanban.assigneeUnassigned")}</option>
    </select>
  );
};
