import { useCallback, useEffect, useState } from "react";
import { HermesApiError } from "@/lib/api";
import {
  createProject,
  deleteProject,
  listProjects,
  renameProject,
} from "../api/projectsApi";
import type { HermesProject, ProjectFilter } from "../types";
import { NO_PROJECT_FILTER, PROJECT_COLORS } from "../types";

export function useProjects() {
  const [projects, setProjects] = useState<HermesProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<ProjectFilter>(null);
  const [actionPending, setActionPending] = useState(false);

  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listProjects();
      setProjects(data.projects ?? []);
    } catch (err) {
      const message =
        err instanceof HermesApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to load projects";
      setError(message);
      setProjects([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const createNewProject = useCallback(
    async (name: string) => {
      if (!name.trim()) return null;
      setActionPending(true);
      try {
        const color = PROJECT_COLORS[projects.length % PROJECT_COLORS.length];
        const res = await createProject(name, color);
        if (res.project) {
          setProjects((prev) => [...prev, res.project!]);
          return res.project;
        }
        return null;
      } catch {
        return null;
      } finally {
        setActionPending(false);
      }
    },
    [projects.length],
  );

  const renameExistingProject = useCallback(
    async (projectId: string, name: string) => {
      if (!name.trim()) return false;
      setActionPending(true);
      try {
        const res = await renameProject(projectId, name);
        if (res.project) {
          setProjects((prev) =>
            prev.map((p) => (p.project_id === projectId ? res.project! : p)),
          );
          return true;
        }
        return false;
      } catch {
        return false;
      } finally {
        setActionPending(false);
      }
    },
    [],
  );

  const updateProjectColor = useCallback(
    async (project: HermesProject, color: string) => {
      setActionPending(true);
      try {
        const res = await renameProject(project.project_id, project.name, color);
        if (res.project) {
          setProjects((prev) =>
            prev.map((p) => (p.project_id === project.project_id ? res.project! : p)),
          );
        }
      } finally {
        setActionPending(false);
      }
    },
    [],
  );

  const removeProject = useCallback(
    async (projectId: string) => {
      setActionPending(true);
      try {
        await deleteProject(projectId);
        setProjects((prev) => prev.filter((p) => p.project_id !== projectId));
        if (activeFilter === projectId) {
          setActiveFilter(null);
        }
        return true;
      } catch {
        return false;
      } finally {
        setActionPending(false);
      }
    },
    [activeFilter],
  );

  const matchesProjectFilter = useCallback(
    (projectId: string | null | undefined) => {
      if (activeFilter === null) return true;
      if (activeFilter === NO_PROJECT_FILTER) return !projectId;
      return projectId === activeFilter;
    },
    [activeFilter],
  );

  return {
    projects,
    loading,
    error,
    activeFilter,
    setActiveFilter,
    actionPending,
    loadProjects,
    createNewProject,
    renameExistingProject,
    updateProjectColor,
    removeProject,
    matchesProjectFilter,
    NO_PROJECT_FILTER,
  };
}
