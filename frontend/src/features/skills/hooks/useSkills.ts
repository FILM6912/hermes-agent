import { useCallback, useEffect, useMemo, useState } from "react";
import { toastMessage, useToast } from "@/components/toast/ToastProvider";
import { useAuthRole } from "@/features/auth/hooks/useAuthRole";
import { HermesApiError } from "@/lib/api";
import {
  deleteSkill,
  fetchSkillContent,
  fetchSkillsHubPreview,
  installSkillFromHub,
  listSkills,
  saveSkill,
  searchSkillsHub,
  toggleSkill,
} from "../api/skillsApi";
import type { HermesSkill, SkillsHubGroup, SkillsHubResult } from "../types";

function groupHubResults(results: SkillsHubResult[]): SkillsHubGroup[] {
  const buckets = new Map<string, SkillsHubResult[]>();
  for (const row of results) {
    const repo = row.repo?.trim() || "unknown";
    const list = buckets.get(repo) ?? [];
    list.push(row);
    buckets.set(repo, list);
  }
  return [...buckets.entries()].map(([repo, skills]) => ({
    repo,
    skill_count: skills.length,
    total_installs: skills.reduce(
      (sum, skill) => sum + (typeof skill.installs === "number" ? skill.installs : 0),
      0,
    ) || null,
    skills,
  }));
}

function skillApiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof HermesApiError) return err.message;
  const message = toastMessage(err);
  return message && message !== "[object Object]" ? message : fallback;
}

export function useSkills() {
  const { isAdmin } = useAuthRole();
  const toast = useToast();
  const [skills, setSkills] = useState<HermesSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [detailContent, setDetailContent] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [togglePending, setTogglePending] = useState<string | null>(null);
  const [bulkActionPending, setBulkActionPending] = useState<
    "enable" | "disable" | "delete" | null
  >(null);

  const [hubQuery, setHubQuery] = useState("");
  const [hubResults, setHubResults] = useState<SkillsHubResult[]>([]);
  const [hubGroups, setHubGroups] = useState<SkillsHubGroup[]>([]);
  const [hubLoading, setHubLoading] = useState(false);
  const [hubError, setHubError] = useState<string | null>(null);
  const [selectedHub, setSelectedHub] = useState<SkillsHubResult | null>(null);
  const [hubDetailLoading, setHubDetailLoading] = useState(false);
  const [hubDetailError, setHubDetailError] = useState<string | null>(null);
  const [hubDetailContent, setHubDetailContent] = useState<string | null>(null);
  const [installPending, setInstallPending] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<"create" | "edit" | null>(null);
  const [formName, setFormName] = useState("");
  const [formCategory, setFormCategory] = useState("");
  const [formContent, setFormContent] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [savePending, setSavePending] = useState(false);
  const [deletePending, setDeletePending] = useState(false);

  const selectedSkill = useMemo(
    () => skills.find((skill) => skill.name === selectedName) ?? null,
    [skills, selectedName],
  );

  const skillIsMutable = useCallback(
    (skill: Pick<HermesSkill, "readonly"> | null | undefined) =>
      Boolean(skill && (isAdmin || !skill.readonly)),
    [isAdmin],
  );

  const loadSkills = useCallback(async (): Promise<HermesSkill[]> => {
    setLoading(true);
    setError(null);
    try {
      const data = await listSkills();
      const rows = data.skills ?? [];
      setSkills(rows);
      return rows;
    } catch (err) {
      const message = skillApiErrorMessage(err, "Failed to load skills");
      setError(message);
      toast.error(message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void loadSkills();
  }, [loadSkills]);

  const filteredSkills = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.description ?? "").toLowerCase().includes(q) ||
        (s.category ?? "").toLowerCase().includes(q),
    );
  }, [skills, searchQuery]);

  const skillsByCategory = useMemo(() => {
    const cats: Record<string, HermesSkill[]> = {};
    for (const skill of filteredSkills) {
      const cat = skill.category || "(general)";
      if (!cats[cat]) cats[cat] = [];
      cats[cat].push(skill);
    }
    for (const items of Object.values(cats)) {
      items.sort((a, b) => a.name.localeCompare(b.name));
    }
    return Object.entries(cats).sort(([a], [b]) => a.localeCompare(b));
  }, [filteredSkills]);

  const openSkill = useCallback(async (name: string) => {
    setSelectedHub(null);
    setHubDetailContent(null);
    setHubDetailError(null);
    setSelectedName(name);
    setFormMode(null);
    setFormError(null);
    setDetailContent(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const data = await fetchSkillContent(name);
      if (data.error || data.success === false) {
        const message = data.error ?? "Failed to load skill";
        setDetailError(message);
        toast.error(message);
        return;
      }
      setDetailContent(data.content ?? "");
    } catch (err) {
      const message = skillApiErrorMessage(err, "Failed to load skill");
      setDetailError(message);
      toast.error(message);
    } finally {
      setDetailLoading(false);
    }
  }, [toast]);

  const openHubSkill = useCallback(async (row: SkillsHubResult) => {
    setSelectedName(null);
    setFormMode(null);
    setDetailContent(null);
    setDetailError(null);
    setSelectedHub(row);
    setHubDetailContent(null);
    setHubDetailError(null);
    setHubDetailLoading(true);
    try {
      const data = await fetchSkillsHubPreview(row.identifier);
      if (data.success === false || !data.content?.trim()) {
        const message =
          data.error ??
          (data.success === false ? "Skill not found" : "Failed to load skill preview");
        setHubDetailError(message);
        toast.error(message);
        return;
      }
      setHubDetailContent(data.content);
    } catch (err) {
      const message = skillApiErrorMessage(err, "Failed to load skill preview");
      setHubDetailError(message);
      toast.error(message);
    } finally {
      setHubDetailLoading(false);
    }
  }, [toast]);

  const clearHubSelection = useCallback(() => {
    setSelectedHub(null);
    setHubDetailContent(null);
    setHubDetailError(null);
  }, []);

  const handleToggle = useCallback(
    async (name: string, currentlyEnabled: boolean) => {
      setTogglePending(name);
      try {
        const result = await toggleSkill(name, !currentlyEnabled);
        if (result.ok !== false) {
          setSkills((prev) =>
            prev.map((s) =>
              s.name === name ? { ...s, disabled: currentlyEnabled } : s,
            ),
          );
        } else if (result.error) {
          toast.error(result.error);
        }
      } catch (err) {
        toast.error(skillApiErrorMessage(err, `Failed to toggle skill "${name}"`));
      } finally {
        setTogglePending(null);
      }
    },
    [toast],
  );

  const bulkEnableSkills = useCallback(
    async (names: string[]) => {
      const toEnable = names.filter((name) => {
        const skill = skills.find((item) => item.name === name);
        return skill?.disabled;
      });
      if (toEnable.length === 0) return true;

      setBulkActionPending("enable");
      const updated = new Set<string>();
      const failures: string[] = [];
      try {
        for (const name of toEnable) {
          setTogglePending(name);
          try {
            const result = await toggleSkill(name, true);
            if (result.ok !== false) {
              updated.add(name);
            } else {
              failures.push(result.error ?? `Failed to enable "${name}"`);
            }
          } catch (err) {
            failures.push(skillApiErrorMessage(err, `Failed to enable "${name}"`));
          }
        }
        if (updated.size > 0) {
          setSkills((prev) =>
            prev.map((skill) =>
              updated.has(skill.name) ? { ...skill, disabled: false } : skill,
            ),
          );
          toast.success(`Enabled ${updated.size} skill${updated.size === 1 ? "" : "s"}.`);
        }
        if (failures.length > 0) {
          toast.error(
            failures.length === 1
              ? failures[0]
              : `Failed to enable ${failures.length} skills. ${failures[0]}`,
          );
        }
        return updated.size === toEnable.length;
      } catch (err) {
        toast.error(skillApiErrorMessage(err, "Bulk enable failed"));
        return false;
      } finally {
        setTogglePending(null);
        setBulkActionPending(null);
      }
    },
    [skills, toast],
  );

  const bulkDisableSkills = useCallback(
    async (names: string[]) => {
      const toDisable = names.filter((name) => {
        const skill = skills.find((item) => item.name === name);
        return skill && !skill.disabled;
      });
      if (toDisable.length === 0) return true;

      setBulkActionPending("disable");
      const updated = new Set<string>();
      const failures: string[] = [];
      try {
        for (const name of toDisable) {
          setTogglePending(name);
          try {
            const result = await toggleSkill(name, false);
            if (result.ok !== false) {
              updated.add(name);
            } else {
              failures.push(result.error ?? `Failed to disable "${name}"`);
            }
          } catch (err) {
            failures.push(skillApiErrorMessage(err, `Failed to disable "${name}"`));
          }
        }
        if (updated.size > 0) {
          setSkills((prev) =>
            prev.map((skill) =>
              updated.has(skill.name) ? { ...skill, disabled: true } : skill,
            ),
          );
          toast.success(`Disabled ${updated.size} skill${updated.size === 1 ? "" : "s"}.`);
        }
        if (failures.length > 0) {
          toast.error(
            failures.length === 1
              ? failures[0]
              : `Failed to disable ${failures.length} skills. ${failures[0]}`,
          );
        }
        return updated.size === toDisable.length;
      } catch (err) {
        toast.error(skillApiErrorMessage(err, "Bulk disable failed"));
        return false;
      } finally {
        setTogglePending(null);
        setBulkActionPending(null);
      }
    },
    [skills, toast],
  );

  const runHubSearch = useCallback(async () => {
    const q = hubQuery.trim();
    if (!q) {
      setHubResults([]);
      setHubGroups([]);
      return;
    }
    setHubLoading(true);
    setHubError(null);
    try {
      const data = await searchSkillsHub(q);
      const results = data.results ?? [];
      setHubResults(results);
      setHubGroups(
        data.groups && data.groups.length > 0 ? data.groups : groupHubResults(results),
      );
    } catch (err) {
      const message = skillApiErrorMessage(err, "Hub search failed");
      setHubResults([]);
      setHubGroups([]);
      setHubError(message);
      toast.error(message);
    } finally {
      setHubLoading(false);
    }
  }, [hubQuery, toast]);

  const handleInstall = useCallback(
    async (identifier: string): Promise<boolean> => {
      setInstallPending(identifier);
      try {
        const result = await installSkillFromHub(identifier);
        const message =
          result.message ?? (result.ok ? "Installed" : result.error ?? "Install failed");
        if (result.ok !== false) {
          toast.success(message);
          clearHubSelection();
          await loadSkills();
          return true;
        }
        toast.error(message);
        return false;
      } catch (err) {
        const message = skillApiErrorMessage(err, "Install failed");
        toast.error(message);
        return false;
      } finally {
        setInstallPending(null);
      }
    },
    [clearHubSelection, loadSkills, toast],
  );

  const clearSelection = useCallback(() => {
    setSelectedName(null);
    setDetailContent(null);
    setDetailError(null);
    setFormMode(null);
    setFormError(null);
    clearHubSelection();
  }, [clearHubSelection]);

  const bulkDeleteSkills = useCallback(
    async (names: string[]) => {
      const deletable = names.filter((name) => {
        const skill = skills.find((item) => item.name === name);
        return skill && skillIsMutable(skill);
      });
      if (deletable.length === 0) {
        toast.error("No deletable skills in selection.");
        return { deletedCount: 0, skippedCount: 0, failedCount: 0 };
      }

      setBulkActionPending("delete");
      const deleted = new Set<string>();
      const skipped = new Map<string, string>();
      const failed = new Map<string, string>();
      const uniqueNames = [...new Set(deletable)];
      try {
        for (const name of uniqueNames) {
          try {
            const result = await deleteSkill(name);
            if (result.ok !== false) {
              deleted.add(name);
            } else {
              failed.set(name, result.error ?? `Failed to delete "${name}"`);
            }
          } catch (err) {
            if (err instanceof HermesApiError) {
              if (err.status === 404) {
                deleted.add(name);
                continue;
              }
              if (err.status === 403) {
                skipped.set(name, err.message);
                continue;
              }
            }
            failed.set(name, skillApiErrorMessage(err, `Failed to delete "${name}"`));
          }
        }
        if (deleted.size > 0) {
          if (selectedName && deleted.has(selectedName)) {
            clearSelection();
          }
          setSkills((prev) => prev.filter((skill) => !deleted.has(skill.name)));
          let stillPresent: string[] = [];
          try {
            const refreshed = await loadSkills();
            stillPresent = [...deleted].filter((name) =>
              refreshed.some((skill) => skill.name === name),
            );
          } catch {
            stillPresent = [...deleted];
          }
          if (stillPresent.length > 0) {
            failed.set(
              stillPresent[0],
              `Skill still listed after delete (${stillPresent.length} remaining). Refresh or remove files manually.`,
            );
          } else {
            toast.success(
              `Deleted ${deleted.size} skill${deleted.size === 1 ? "" : "s"}.`,
            );
          }
        }
        if (skipped.size > 0) {
          const firstReason = [...skipped.values()][0];
          toast.error(
            skipped.size === 1
              ? firstReason
              : `Could not delete ${skipped.size} skills (read-only or outside profile). ${firstReason}`,
          );
        }
        if (failed.size > 0) {
          const firstReason = [...failed.values()][0];
          toast.error(
            failed.size === 1
              ? firstReason
              : `Failed to delete ${failed.size} skills. ${firstReason}`,
          );
        }
        return {
          deletedCount: deleted.size,
          skippedCount: skipped.size,
          failedCount: failed.size,
        };
      } catch (err) {
        toast.error(skillApiErrorMessage(err, "Bulk delete failed"));
        return {
          deletedCount: deleted.size,
          skippedCount: skipped.size,
          failedCount: failed.size + 1,
        };
      } finally {
        setBulkActionPending(null);
      }
    },
    [clearSelection, loadSkills, selectedName, skillIsMutable, skills, toast],
  );

  const startCreateSkill = useCallback(() => {
    clearHubSelection();
    setSelectedName(null);
    setDetailContent(null);
    setDetailError(null);
    setFormMode("create");
    setFormName("");
    setFormCategory("");
    setFormContent(
      "---\nname: my-skill\ndescription: Short description\n---\n\n# My skill\n\nInstructions here.\n",
    );
    setFormError(null);
  }, []);

  const startEditSkill = useCallback(() => {
    if (!selectedName || !skillIsMutable(selectedSkill)) return;
    setFormMode("edit");
    setFormName(selectedName);
    setFormCategory(selectedSkill?.category ?? "");
    setFormContent(detailContent ?? "");
    setFormError(null);
  }, [detailContent, selectedName, selectedSkill, skillIsMutable]);

  const cancelSkillForm = useCallback(() => {
    setFormMode(null);
    setFormError(null);
    if (selectedName) {
      void openSkill(selectedName);
      return;
    }
    clearSelection();
  }, [clearSelection, openSkill, selectedName]);

  const submitSkillForm = useCallback(async () => {
    const name = formName.trim().toLowerCase().replace(/\s+/g, "-");
    const content = formContent;
    if (!name) {
      setFormError("Skill name is required.");
      return;
    }
    if (!content.trim()) {
      setFormError("Skill content is required.");
      return;
    }
    setSavePending(true);
    setFormError(null);
    try {
      const result = await saveSkill({
        name,
        content,
        category: formCategory.trim() || undefined,
      });
      if (result.ok === false) {
        const message = result.error ?? "Failed to save skill";
        setFormError(message);
        toast.error(message);
        return;
      }
      setFormMode(null);
      toast.success(`Saved skill "${name}".`);
      await loadSkills();
      await openSkill(name);
    } catch (err) {
      const message = skillApiErrorMessage(err, "Failed to save skill");
      setFormError(message);
      toast.error(message);
    } finally {
      setSavePending(false);
    }
  }, [formCategory, formContent, formName, loadSkills, openSkill, toast]);

  const removeSelectedSkill = useCallback(async () => {
    if (!selectedName || !skillIsMutable(selectedSkill)) return false;
    setDeletePending(true);
    try {
      const result = await deleteSkill(selectedName);
      if (result.ok === false) {
        const message = result.error ?? "Failed to delete skill";
        setDetailError(message);
        toast.error(message);
        return false;
      }
      clearSelection();
      setSkills((prev) => prev.filter((skill) => skill.name !== selectedName));
      const refreshed = await loadSkills();
      if (refreshed.some((skill) => skill.name === selectedName)) {
        const message = `Skill "${selectedName}" is still listed after delete.`;
        setDetailError(message);
        toast.error(message);
        return false;
      }
      toast.success(`Deleted skill "${selectedName}".`);
      return true;
    } catch (err) {
      const message = skillApiErrorMessage(err, "Failed to delete skill");
      setDetailError(message);
      toast.error(message);
      return false;
    } finally {
      setDeletePending(false);
    }
  }, [clearSelection, loadSkills, selectedName, selectedSkill, skillIsMutable, toast]);

  return {
    isAdmin,
    skillIsMutable,
    skills,
    loading,
    error,
    searchQuery,
    setSearchQuery,
    skillsByCategory,
    selectedName,
    selectedSkill,
    detailContent,
    detailLoading,
    detailError,
    formMode,
    formName,
    setFormName,
    formCategory,
    setFormCategory,
    formContent,
    setFormContent,
    formError,
    savePending,
    deletePending,
    togglePending,
    bulkActionPending,
    bulkEnableSkills,
    bulkDisableSkills,
    bulkDeleteSkills,
    loadSkills,
    openSkill,
    clearSelection,
    startCreateSkill,
    startEditSkill,
    cancelSkillForm,
    submitSkillForm,
    removeSelectedSkill,
    handleToggle,
    hubQuery,
    setHubQuery,
    hubResults,
    hubGroups,
    hubLoading,
    hubError,
    selectedHub,
    hubDetailContent,
    hubDetailLoading,
    hubDetailError,
    runHubSearch,
    openHubSkill,
    clearHubSelection,
    installPending,
    handleInstall,
  };
}
