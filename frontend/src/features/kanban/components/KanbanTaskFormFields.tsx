import React from "react";
import { useLanguage } from "@/hooks/useLanguage";
import { KANBAN_COLUMNS } from "../types";
import { kanbanStatusLabel } from "../kanbanI18n";
import { KanbanAssigneeSelect } from "./KanbanAssigneeSelect";
import { KanbanPrioritySelect } from "./KanbanPrioritySelect";
import { KanbanWorkspaceSelect } from "./KanbanWorkspaceSelect";
import type { HermesProfileSummary } from "@/services/hermes/profiles";
import type { HermesWorkspace } from "@/services/hermes/workspace";

export type KanbanTaskFormValues = {
  title: string;
  body: string;
  status: string;
  assignee: string;
  workspacePath: string;
  tenant: string;
  priority: number;
};

export type KanbanTaskFormFieldsProps = {
  values: KanbanTaskFormValues;
  onChange: (patch: Partial<KanbanTaskFormValues>) => void;
  profiles: HermesProfileSummary[];
  workspaces?: HermesWorkspace[];
  historicalAssignees?: string[];
  titleAutoFocus?: boolean;
};

export const KanbanTaskFormFields: React.FC<KanbanTaskFormFieldsProps> = ({
  values,
  onChange,
  profiles,
  workspaces = [],
  historicalAssignees,
  titleAutoFocus = false,
}) => {
  const { t } = useLanguage();

  return (
    <div className="space-y-3">
      <label className="block space-y-1">
        <span className="text-xs text-zinc-500">{t("kanban.fieldTitle")}</span>
        <input
          autoFocus={titleAutoFocus}
          value={values.title}
          onChange={(e) => onChange({ title: e.target.value })}
          required
          className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>
      <label className="block space-y-1">
        <span className="text-xs text-zinc-500">{t("kanban.fieldDescription")}</span>
        <textarea
          rows={4}
          value={values.body}
          onChange={(e) => onChange({ body: e.target.value })}
          className="w-full resize-none rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>
      <label className="block space-y-1">
        <span className="text-xs text-zinc-500">{t("kanban.fieldStatus")}</span>
        <select
          value={values.status}
          onChange={(e) => onChange({ status: e.target.value })}
          className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        >
          {KANBAN_COLUMNS.map((s) => (
            <option key={s} value={s}>
              {kanbanStatusLabel(s, t)}
            </option>
          ))}
        </select>
      </label>
      <label className="block space-y-1">
        <span className="text-xs text-zinc-500">{t("kanban.fieldAssignee")}</span>
        <KanbanAssigneeSelect
          value={values.assignee}
          onChange={(assignee) => onChange({ assignee })}
          profiles={profiles}
          historicalAssignees={historicalAssignees}
          className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>
      <label className="block space-y-1">
        <span className="text-xs text-zinc-500">{t("kanban.fieldWorkspace")}</span>
        <KanbanWorkspaceSelect
          workspacePath={values.workspacePath}
          tenant={values.tenant}
          onChange={(patch) => onChange(patch)}
          workspaces={workspaces}
          className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <p className="text-[10px] text-zinc-500">{t("kanban.workspaceHint")}</p>
      </label>
      <label className="block space-y-1">
        <span className="text-xs text-zinc-500">{t("kanban.fieldPriority")}</span>
        <KanbanPrioritySelect
          value={values.priority}
          onChange={(priority) => onChange({ priority })}
          className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <p className="text-[10px] text-zinc-500">{t("kanban.priorityHint")}</p>
      </label>
    </div>
  );
};
