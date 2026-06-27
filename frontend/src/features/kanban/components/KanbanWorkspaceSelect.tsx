import React from "react";
import { useLanguage } from "@/hooks/useLanguage";
import type { HermesWorkspace } from "@/services/hermes/workspace";
import { workspaceDisplayLabel, workspaceTenantSlug } from "../kanbanDispatch";

export const KANBAN_CUSTOM_TENANT = "__custom_tenant__";

export type KanbanWorkspaceSelectProps = {
  workspacePath: string;
  tenant: string;
  onChange: (patch: { workspacePath: string; tenant: string }) => void;
  workspaces: HermesWorkspace[];
  className?: string;
  id?: string;
};

export const KanbanWorkspaceSelect: React.FC<KanbanWorkspaceSelectProps> = ({
  workspacePath,
  tenant,
  onChange,
  workspaces,
  className,
  id,
}) => {
  const { t } = useLanguage();
  const useCustomTenant =
    workspacePath === KANBAN_CUSTOM_TENANT ||
    (!workspacePath && tenant.trim().length > 0);

  const selectValue = useCustomTenant
    ? KANBAN_CUSTOM_TENANT
    : workspacePath || "";

  const handleWorkspaceChange = (value: string) => {
    if (value === KANBAN_CUSTOM_TENANT) {
      onChange({ workspacePath: KANBAN_CUSTOM_TENANT, tenant });
      return;
    }
    if (!value) {
      onChange({ workspacePath: "", tenant: "" });
      return;
    }
    const match = workspaces.find((w) => w.path === value);
    onChange({
      workspacePath: value,
      tenant: workspaceTenantSlug(value, match?.name),
    });
  };

  if (workspaces.length === 0) {
    return (
      <input
        id={id}
        value={tenant}
        onChange={(e) =>
          onChange({ workspacePath: KANBAN_CUSTOM_TENANT, tenant: e.target.value })
        }
        placeholder={t("kanban.tenantPlaceholder")}
        className={className}
      />
    );
  }

  return (
    <div className="space-y-2">
      <select
        id={id}
        value={selectValue}
        onChange={(e) => handleWorkspaceChange(e.target.value)}
        className={className}
      >
        <option value="">{t("kanban.workspacePlaceholder")}</option>
        {workspaces.map((workspace) => (
          <option key={workspace.path} value={workspace.path} title={workspace.path}>
            {workspaceDisplayLabel(workspace.path, workspace.name)}
          </option>
        ))}
        <option value={KANBAN_CUSTOM_TENANT}>{t("kanban.workspaceCustomTenant")}</option>
      </select>
      {useCustomTenant && (
        <input
          value={tenant}
          onChange={(e) =>
            onChange({ workspacePath: KANBAN_CUSTOM_TENANT, tenant: e.target.value })
          }
          placeholder={t("kanban.tenantPlaceholder")}
          className={className}
        />
      )}
    </div>
  );
};
