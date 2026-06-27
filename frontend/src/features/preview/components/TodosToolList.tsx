import React from "react";
import { Circle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import type { TodoItem, TodoItemStatus } from "@/features/preview/utils/parseTodosToolPayload";

const STATUS_META: Record<
  TodoItemStatus,
  { label: string; className: string; iconClassName: string; icon: React.ReactNode }
> = {
  pending: {
    label: "Pending",
    className:
      "bg-zinc-200/80 text-zinc-700 dark:bg-zinc-800/80 dark:text-zinc-300 border-zinc-300/60 dark:border-zinc-700/60",
    iconClassName: "text-zinc-400 dark:text-zinc-500",
    icon: <Circle className="h-3 w-3 shrink-0" aria-hidden />,
  },
  in_progress: {
    label: "In progress",
    className:
      "bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/25 dark:border-blue-400/30 animate-pulse",
    iconClassName: "text-blue-500 dark:text-blue-400",
    icon: <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden />,
  },
  completed: {
    label: "Done",
    className:
      "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/25 dark:border-emerald-400/30",
    iconClassName: "text-emerald-500 dark:text-emerald-400",
    icon: <CheckCircle2 className="h-3 w-3 shrink-0" aria-hidden />,
  },
  cancelled: {
    label: "Cancelled",
    className:
      "bg-zinc-200/60 text-zinc-500 dark:bg-zinc-800/50 dark:text-zinc-500 border-zinc-300/40 dark:border-zinc-700/50",
    iconClassName: "text-zinc-400 dark:text-zinc-500",
    icon: <XCircle className="h-3 w-3 shrink-0" aria-hidden />,
  },
};

function rowClassName(status: TodoItemStatus): string {
  const base =
    "flex gap-3 rounded-md border px-3 py-2.5 transition-all duration-300 ease-out animate-in fade-in slide-in-from-bottom-1 fill-mode-backwards";
  if (status === "in_progress") {
    return `${base} border-blue-500/30 bg-blue-500/[0.06] dark:bg-blue-500/10 shadow-[0_0_0_1px_rgba(59,130,246,0.08)]`;
  }
  if (status === "completed") {
    return `${base} border-emerald-500/20 bg-white/60 dark:bg-zinc-950/40`;
  }
  return `${base} border-zinc-200/60 dark:border-zinc-800/50 bg-white/60 dark:bg-zinc-950/40`;
}

interface TodosToolListProps {
  items: TodoItem[];
}

export const TodosToolList: React.FC<TodosToolListProps> = ({ items }) => {
  if (!items.length) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground italic px-1 py-2 animate-in fade-in duration-300">
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin opacity-70" aria-hidden />
        Loading tasks…
      </p>
    );
  }

  return (
    <ul
      className="space-y-2 rounded-lg border border-zinc-200/80 dark:border-zinc-800/60 bg-zinc-50 dark:bg-zinc-900/50 p-3 animate-in fade-in slide-in-from-top-1 duration-300"
      role="list"
      aria-label="Task list"
    >
      {items.map((item, index) => {
        const meta = STATUS_META[item.status];
        const cancelled = item.status === "cancelled";
        const completed = item.status === "completed";
        const inProgress = item.status === "in_progress";
        return (
          <li
            key={item.id}
            className={rowClassName(item.status)}
            style={{ animationDelay: `${index * 70}ms` }}
          >
            <div className={`mt-0.5 shrink-0 transition-colors duration-300 ${meta.iconClassName}`}>
              {meta.icon}
            </div>
            <div className="min-w-0 flex-1">
              <p
                className={`text-sm leading-relaxed text-zinc-800 dark:text-zinc-200 whitespace-pre-wrap break-words transition-opacity duration-300 ${
                  cancelled ? "line-through opacity-60" : ""
                } ${completed ? "opacity-90" : ""} ${inProgress ? "text-zinc-900 dark:text-zinc-100" : ""}`}
              >
                {item.content}
              </p>
              <span className="mt-1.5 block font-mono text-[10px] text-zinc-400 dark:text-zinc-600 truncate">
                {item.id}
              </span>
            </div>
            <span
              className={`shrink-0 self-start rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition-all duration-300 ${meta.className}`}
            >
              {meta.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
};
