import React, { useRef, useState } from "react";
import { Loader2, MoreHorizontal, Plus } from "lucide-react";
import type { HermesProject } from "../types";
import { PROJECT_COLORS, type ProjectFilter } from "../types";

interface ProjectsBarProps {
  projects: HermesProject[];
  activeFilter: ProjectFilter;
  onFilterChange: (filter: ProjectFilter) => void;
  loading?: boolean;
  actionPending?: boolean;
  onCreateProject: (name: string) => Promise<unknown>;
  onRenameProject: (projectId: string, name: string) => Promise<boolean>;
  onUpdateColor: (project: HermesProject, color: string) => Promise<void>;
  onDeleteProject: (projectId: string) => Promise<boolean>;
}

export const ProjectsBar: React.FC<ProjectsBarProps> = ({
  projects,
  activeFilter,
  onFilterChange,
  loading,
  actionPending,
  onCreateProject,
  onRenameProject,
  onUpdateColor,
  onDeleteProject,
}) => {
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [menuProject, setMenuProject] = useState<HermesProject | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  if (loading) {
    return (
      <div className="mb-3 flex items-center gap-2 px-1">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" />
        <span className="text-[10px] text-zinc-500">Loading projects…</span>
      </div>
    );
  }

  if (projects.length === 0) {
    return null;
  }

  const chipClass = (active: boolean) =>
    `inline-flex max-w-[140px] shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors ${
      active
        ? "border-indigo-500/50 bg-indigo-50 text-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-200"
        : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400"
    }`;

  return (
    <div className="mb-3 px-1">
      <div className="flex flex-wrap items-center gap-1.5">
        {projects.map((project) => {
          const isRenaming = renamingId === project.project_id;
          if (isRenaming) {
            return (
              <input
                key={project.project_id}
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && renameValue.trim()) {
                    void onRenameProject(project.project_id, renameValue).then((ok) => {
                      if (ok) setRenamingId(null);
                    });
                  }
                  if (e.key === "Escape") setRenamingId(null);
                }}
                onBlur={() => {
                  if (renameValue.trim() && renameValue.trim() !== project.name) {
                    void onRenameProject(project.project_id, renameValue).then(() =>
                      setRenamingId(null),
                    );
                  } else {
                    setRenamingId(null);
                  }
                }}
                className="max-w-[120px] rounded-full border border-indigo-400 px-2 py-0.5 text-[10px] dark:bg-zinc-900"
              />
            );
          }
          return (
            <button
              key={project.project_id}
              type="button"
              className={chipClass(activeFilter === project.project_id)}
              onClick={() => onFilterChange(project.project_id)}
              onDoubleClick={(e) => {
                e.preventDefault();
                setRenamingId(project.project_id);
                setRenameValue(project.name);
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                setMenuProject(project);
              }}
            >
              {project.color && (
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: project.color }}
                />
              )}
              <span className="truncate">{project.name}</span>
            </button>
          );
        })}
        {creating ? (
          <input
            autoFocus
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && createName.trim()) {
                void onCreateProject(createName).then(() => {
                  setCreating(false);
                  setCreateName("");
                });
              }
              if (e.key === "Escape") {
                setCreating(false);
                setCreateName("");
              }
            }}
            onBlur={() => {
              if (createName.trim()) {
                void onCreateProject(createName).then(() => {
                  setCreating(false);
                  setCreateName("");
                });
              } else {
                setCreating(false);
              }
            }}
            placeholder="Name"
            className="max-w-[100px] rounded-full border border-zinc-200 px-2 py-0.5 text-[10px] dark:border-zinc-700 dark:bg-zinc-900"
          />
        ) : (
          <button
            type="button"
            disabled={actionPending}
            onClick={() => setCreating(true)}
            className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-zinc-300 text-zinc-500 hover:border-zinc-400 hover:text-zinc-700 dark:border-zinc-600"
            title="New project"
          >
            <Plus className="h-3 w-3" />
          </button>
        )}
      </div>

      {menuProject && (
        <div
          ref={menuRef}
          className="fixed z-[200] min-w-[160px] rounded-lg border border-zinc-200 bg-white py-1 shadow-xl dark:border-zinc-700 dark:bg-zinc-900"
          style={{ left: 80, top: 200 }}
        >
          <div className="px-3 py-2 text-xs font-medium text-zinc-500">{menuProject.name}</div>
          <div className="flex flex-wrap gap-1.5 px-3 pb-2">
            {PROJECT_COLORS.map((hex) => (
              <button
                key={hex}
                type="button"
                className="h-4 w-4 rounded-full border border-zinc-300 dark:border-zinc-600"
                style={{
                  backgroundColor: hex,
                  outline: menuProject.color === hex ? "2px solid currentColor" : undefined,
                }}
                onClick={() => {
                  void onUpdateColor(menuProject, hex);
                  setMenuProject(null);
                }}
              />
            ))}
          </div>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800"
            onClick={() => {
              setRenamingId(menuProject.project_id);
              setRenameValue(menuProject.name);
              setMenuProject(null);
            }}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
            Rename
          </button>
          <button
            type="button"
            className="flex w-full px-3 py-2 text-left text-xs text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30"
            onClick={() => {
              const name = menuProject.name;
              const id = menuProject.project_id;
              setMenuProject(null);
              if (window.confirm(`Delete project "${name}"? Sessions will be unassigned.`)) {
                void onDeleteProject(id);
              }
            }}
          >
            Delete
          </button>
          <button
            type="button"
            className="w-full px-3 py-1 text-center text-[10px] text-zinc-400"
            onClick={() => setMenuProject(null)}
          >
            Close
          </button>
        </div>
      )}
    </div>
  );
};
