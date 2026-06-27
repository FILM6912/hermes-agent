import React, { useMemo } from "react";
import { useLanguage } from "@/hooks/useLanguage";
import { KANBAN_PRIORITY_LEVELS, kanbanPriorityLabel } from "../kanbanI18n";

export type KanbanPrioritySelectProps = {
  value: number;
  onChange: (value: number) => void;
  className?: string;
  disabled?: boolean;
};

export const KanbanPrioritySelect: React.FC<KanbanPrioritySelectProps> = ({
  value,
  onChange,
  className = "",
  disabled = false,
}) => {
  const { t } = useLanguage();
  const safeValue = Number.isNaN(Number(value)) ? 0 : Number(value);

  const options = useMemo(() => {
    const levels: Array<{ value: number; label: string }> = KANBAN_PRIORITY_LEVELS.map((level) => ({
      value: level.value,
      label: t(level.labelKey),
    }));
    if (!levels.some((level) => level.value === safeValue)) {
      levels.push({
        value: safeValue,
        label: kanbanPriorityLabel(safeValue, t),
      });
    }
    return levels;
  }, [safeValue, t]);

  return (
    <select
      value={String(safeValue)}
      onChange={(e) => onChange(Number.parseInt(e.target.value, 10) || 0)}
      disabled={disabled}
      className={className}
      aria-label={t("kanban.fieldPriority")}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
};
