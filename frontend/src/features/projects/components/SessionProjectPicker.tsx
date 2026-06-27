import React, { useEffect, useRef, useState } from "react";
import { FolderInput, Loader2 } from "lucide-react";
import { moveSessionToProject } from "../api/projectsApi";
import type { HermesProject } from "../types";
interface SessionProjectPickerProps {
  sessionId: string;
  currentProjectId?: string | null;
  projects: HermesProject[];
  onMoved: (projectId: string | null) => void;
  onCreateAndMove: (name: string) => Promise<HermesProject | null>;
}

export const SessionProjectPicker: React.FC<SessionProjectPickerProps> = ({
  sessionId,
  currentProjectId,
  projects,
  onMoved,
  onCreateAndMove,
}) => {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const moveTo = async (projectId: string | null) => {
    setPending(true);
    try {
      await moveSessionToProject(sessionId, projectId);
      onMoved(projectId);
      setOpen(false);
    } catch {
      /* ignore */
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        disabled={pending}
        className="sidebar-delete absolute right-16 p-1.5 text-zinc-400 opacity-0 transition-all group-hover:opacity-100 hover:bg-zinc-500/10 hover:text-indigo-500 rounded-md"
        title="Move to project"
      >
        {pending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <FolderInput className="h-3.5 w-3.5" />
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 min-w-[180px] rounded-lg border border-zinc-200 bg-white py-1 shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
          <button
            type="button"
            className={`w-full px-3 py-2 text-left text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 ${
              !currentProjectId ? "font-medium text-indigo-600" : ""
            }`}
            onClick={() => void moveTo(null)}
          >
            No project
          </button>
          {projects.map((p) => (
            <button
              key={p.project_id}
              type="button"
              className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 ${
                currentProjectId === p.project_id ? "font-medium text-indigo-600" : ""
              }`}
              onClick={() => void moveTo(p.project_id)}
            >
              {p.color && (
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: p.color }}
                />
              )}
              <span className="truncate">{p.name}</span>
            </button>
          ))}
          <button
            type="button"
            className="w-full border-t border-zinc-100 px-3 py-2 text-left text-xs text-indigo-600 hover:bg-zinc-100 dark:border-zinc-800 dark:hover:bg-zinc-800"
            onClick={() => {
              const name = window.prompt("Project name:");
              if (!name?.trim()) return;
              void (async () => {
                setPending(true);
                try {
                  const project = await onCreateAndMove(name.trim());
                  if (project) {
                    await moveSessionToProject(sessionId, project.project_id);
                    onMoved(project.project_id);
                    setOpen(false);
                  }
                } finally {
                  setPending(false);
                }
              })();
            }}
          >
            + New project
          </button>
        </div>
      )}
    </div>
  );
};
