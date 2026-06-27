import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Download,
  Layers,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { ConfirmModal } from "@/components/ConfirmModal";
import { useSkills } from "../hooks/useSkills";
import type { SkillsHubGroup, SkillsHubResult } from "../types";
import { SkillMarkdownView } from "./SkillMarkdownView";

interface SkillsPanelProps {
  onBack: () => void;
}

function hubRepoInstallIdentifier(repo: string): string {
  return `skills-sh/${repo}`;
}

function formatInstallCount(value?: number | null): string {
  if (typeof value !== "number" || value <= 0) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

function formatCategoryLabel(category: string): string {
  const raw = category.replace(/^\(|\)$/g, "").trim();
  if (!raw) return "General";
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function applySkillListSelection(
  name: string,
  orderedNames: string[],
  previous: Set<string>,
  anchor: string | null,
  shiftKey: boolean,
  multiKey: boolean,
): { next: Set<string>; anchor: string } {
  if (shiftKey && anchor && orderedNames.includes(anchor)) {
    const start = orderedNames.indexOf(anchor);
    const end = orderedNames.indexOf(name);
    if (start === -1 || end === -1) {
      return { next: new Set([name]), anchor: name };
    }
    const [lo, hi] = start < end ? [start, end] : [end, start];
    const range = orderedNames.slice(lo, hi + 1);
    if (multiKey) {
      const next = new Set(previous);
      for (const item of range) next.add(item);
      return { next, anchor };
    }
    return { next: new Set(range), anchor };
  }

  if (multiKey) {
    const next = new Set(previous);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    return { next, anchor: name };
  }

  return { next: new Set([name]), anchor: name };
}

function SkillToggle({
  enabled,
  pending,
  onToggle,
}: {
  enabled: boolean;
  pending: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      disabled={pending}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      role="switch"
      aria-checked={enabled}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/50 disabled:opacity-50 ${
        enabled
          ? "bg-violet-600 dark:bg-violet-500"
          : "bg-zinc-300 dark:bg-zinc-600"
      }`}
      title={enabled ? "Disable skill" : "Enable skill"}
    >
      <span
        className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
          enabled ? "translate-x-4" : "translate-x-0"
        }`}
      />
      {pending && (
        <span className="absolute inset-0 flex items-center justify-center">
          <Loader2 className="h-3 w-3 animate-spin text-white/80" />
        </span>
      )}
    </button>
  );
}

export const SkillsPanel: React.FC<SkillsPanelProps> = ({ onBack }) => {
  const {
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
    isAdmin,
    skillIsMutable,
  } = useSkills();

  const [collapsedCats, setCollapsedCats] = useState<Set<string>>(new Set());
  const [collapsedHubRepos, setCollapsedHubRepos] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState<"installed" | "hub">("installed");
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const installAndShow = useCallback(
    async (identifier: string) => {
      const ok = await handleInstall(identifier);
      if (ok) {
        setTab("installed");
        setSearchQuery("");
      }
    },
    [handleInstall, setSearchQuery],
  );

  useEffect(() => {
    if (tab === "installed") {
      void loadSkills();
    }
  }, [tab, loadSkills]);
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const [checkedSkillNames, setCheckedSkillNames] = useState<Set<string>>(
    () => new Set(),
  );
  const [selectionAnchor, setSelectionAnchor] = useState<string | null>(null);

  const orderedSkillNames = useMemo(
    () => skillsByCategory.flatMap(([, items]) => items.map((skill) => skill.name)),
    [skillsByCategory],
  );

  const showGroupedHub = useMemo(
    () => hubGroups.some((group) => group.skill_count > 1) || hubGroups.length > 1,
    [hubGroups],
  );

  const renderHubSkillRow = (row: SkillsHubResult, compact = false) => {
    const isSelected = selectedHub?.identifier === row.identifier;
    if (compact) {
      return (
        <li
          key={row.identifier}
          className={`flex items-center gap-2 border-t border-zinc-100 px-3 py-2.5 first:border-t-0 dark:border-zinc-800 ${
            isSelected ? "bg-violet-50/80 dark:bg-violet-950/30" : ""
          }`}
        >
          <button
            type="button"
            onClick={() => void openHubSkill(row)}
            className="min-w-0 flex-1 text-left"
          >
            <div className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
              {row.name}
            </div>
          </button>
          <span className="shrink-0 text-xs tabular-nums text-zinc-400">
            {formatInstallCount(row.installs)}
          </span>
          <button
            type="button"
            disabled={installPending === row.identifier}
            onClick={() => void installAndShow(row.identifier)}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-violet-600 px-2.5 py-1 text-[11px] font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-50"
          >
            {installPending === row.identifier ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Download className="h-3 w-3" />
            )}
            Install
          </button>
        </li>
      );
    }

    return (
      <li key={row.identifier}>
        <div
          className={`rounded-xl border transition-colors ${
            isSelected
              ? "border-violet-500/40 bg-violet-50/80 dark:border-violet-500/30 dark:bg-violet-950/30"
              : "border-zinc-200/80 bg-white hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900/40 dark:hover:border-zinc-700"
          }`}
        >
          <button
            type="button"
            onClick={() => void openHubSkill(row)}
            className="w-full p-4 text-left"
          >
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                {row.name}
              </div>
              {row.source === "skills.sh" && (
                <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-violet-700 uppercase dark:bg-violet-950/50 dark:text-violet-300">
                  skills.sh
                </span>
              )}
              {typeof row.installs === "number" && (
                <span className="text-[10px] tabular-nums text-zinc-400">
                  {formatInstallCount(row.installs)} installs
                </span>
              )}
            </div>
            {row.description && (
              <p className="mt-1.5 line-clamp-3 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
                {row.description}
              </p>
            )}
            <div className="mt-3 truncate font-mono text-[11px] text-zinc-400">
              {row.identifier}
            </div>
          </button>
          <div className="flex items-center justify-end border-t border-zinc-100 px-4 py-3 dark:border-zinc-800">
            <button
              type="button"
              disabled={installPending === row.identifier}
              onClick={() => void installAndShow(row.identifier)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-50"
            >
              {installPending === row.identifier ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              Install
            </button>
          </div>
        </div>
      </li>
    );
  };

  const renderHubGroup = (group: SkillsHubGroup) => {
    const collapsed = collapsedHubRepos.has(group.repo);
    const skillsShUrl = `https://skills.sh/${group.repo}`;
    const repoInstallId = hubRepoInstallIdentifier(group.repo);
    const repoInstallPending = installPending === repoInstallId;
    const totalInstalls =
      typeof group.total_installs === "number" && group.total_installs > 0
        ? formatInstallCount(group.total_installs)
        : null;

    const toggleGroupCollapsed = () => {
      setCollapsedHubRepos((prev) => {
        const next = new Set(prev);
        if (next.has(group.repo)) next.delete(group.repo);
        else next.add(group.repo);
        return next;
      });
    };

    return (
      <section
        key={group.repo}
        className="overflow-hidden rounded-xl border border-zinc-200/80 bg-white dark:border-zinc-800 dark:bg-zinc-900/40"
      >
        <div className="flex items-start gap-2 px-4 py-3">
          <button
            type="button"
            onClick={toggleGroupCollapsed}
            className="mt-0.5 shrink-0 rounded p-0.5 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
            aria-label={collapsed ? "Expand group" : "Collapse group"}
          >
            {collapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
          <button
            type="button"
            onClick={toggleGroupCollapsed}
            className="min-w-0 flex-1 text-left transition-colors hover:opacity-90"
          >
            <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {group.repo}
            </div>
            <p className="mt-0.5 text-xs text-zinc-500">
              {group.skill_count} skill{group.skill_count === 1 ? "" : "s"}
              {totalInstalls ? ` · ${totalInstalls} total installs` : ""}
            </p>
            <p className="mt-2 truncate font-mono text-[11px] text-zinc-400">
              npx skills add {group.repo}
            </p>
          </button>
          <div className="flex shrink-0 flex-col items-end gap-2">
            <a
              href={skillsShUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[11px] text-violet-600 hover:underline dark:text-violet-400"
            >
              skills.sh
            </a>
            <button
              type="button"
              disabled={repoInstallPending || Boolean(installPending)}
              onClick={() => void installAndShow(repoInstallId)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-50"
            >
              {repoInstallPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              Install all
            </button>
          </div>
        </div>
        {!collapsed && (
          <ul className="border-t border-zinc-100 dark:border-zinc-800">
            {group.skills.map((row) => renderHubSkillRow(row, true))}
          </ul>
        )}
      </section>
    );
  };

  const checkedSkillList = useMemo(
    () => Array.from(checkedSkillNames),
    [checkedSkillNames],
  );

  const selectedDeletableCount = useMemo(
    () =>
      checkedSkillList.filter((name) => {
        const skill = skillsByCategory
          .flatMap(([, items]) => items)
          .find((item) => item.name === name);
        return skillIsMutable(skill);
      }).length,
    [checkedSkillList, skillIsMutable, skillsByCategory],
  );

  useEffect(() => {
    setCheckedSkillNames(new Set());
    setSelectionAnchor(null);
  }, [searchQuery]);

  useEffect(() => {
    setCollapsedHubRepos(new Set());
  }, [hubQuery, hubGroups]);

  const clearCheckedSkills = () => {
    setCheckedSkillNames(new Set());
    setSelectionAnchor(null);
  };

  const handleSkillListClick = (
    name: string,
    event: React.MouseEvent<HTMLButtonElement>,
  ) => {
    const multiKey = event.ctrlKey || event.metaKey;
    if (event.shiftKey || multiKey) {
      event.preventDefault();
      const { next, anchor } = applySkillListSelection(
        name,
        orderedSkillNames,
        checkedSkillNames,
        selectionAnchor,
        event.shiftKey,
        multiKey,
      );
      setCheckedSkillNames(next);
      setSelectionAnchor(anchor);
      return;
    }

    setCheckedSkillNames(new Set([name]));
    setSelectionAnchor(name);
    openSkillDetail(name);
  };

  const toggleCategory = (cat: string) => {
    setCollapsedCats((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const openSkillDetail = (name: string) => {
    void openSkill(name);
  };

  const showMobileDetail = Boolean(selectedName || formMode || selectedHub);

  const renderSkillForm = () => (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void submitSkillForm();
      }}
    >
      <div>
        <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
          Name
        </label>
        <input
          type="text"
          value={formName}
          onChange={(e) => setFormName(e.target.value)}
          disabled={formMode === "edit"}
          placeholder="my-skill"
          className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900"
        />
        {formMode === "edit" && (
          <p className="mt-1 text-xs text-zinc-500">
            Renaming is not supported. Create a new skill to rename.
          </p>
        )}
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
          Category
        </label>
        <input
          type="text"
          value={formCategory}
          onChange={(e) => setFormCategory(e.target.value)}
          placeholder="Optional, e.g. devops"
          className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
          SKILL.md content
        </label>
        <textarea
          value={formContent}
          onChange={(e) => setFormContent(e.target.value)}
          rows={18}
          className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-xs leading-relaxed outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </div>
      {formError && (
        <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {formError}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={cancelSkillForm}
          className="rounded-lg border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={savePending}
          className="inline-flex items-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-50"
        >
          {savePending && <Loader2 className="h-4 w-4 animate-spin" />}
          Save skill
        </button>
      </div>
    </form>
  );

  return (
    <div className="flex h-full w-full flex-col bg-zinc-50 text-zinc-900 dark:bg-[#09090b] dark:text-zinc-200">
      <header className="flex shrink-0 items-center gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg p-2 text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
          aria-label="Back to chat"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-violet-500/10">
          <Layers className="h-5 w-5 text-violet-500" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold tracking-tight">Skills</h1>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
            Enable skills and install from the hub
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadSkills()}
          disabled={loading}
          className="rounded-lg p-2 text-zinc-600 transition-colors hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label="Refresh skills"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
        <button
          type="button"
          onClick={startCreateSkill}
          className="rounded-lg p-2 text-zinc-600 transition-colors hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label="New skill"
        >
          <Plus className="h-4 w-4" />
        </button>
      </header>

      <div className="shrink-0 px-4 py-3">
        <div
          className="flex rounded-lg bg-zinc-100 p-1 dark:bg-zinc-900"
          role="tablist"
          aria-label="Skills views"
        >
          <button
            type="button"
            role="tab"
            aria-selected={tab === "installed"}
            onClick={() => setTab("installed")}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              tab === "installed"
                ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-100"
                : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
            }`}
          >
            Installed
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "hub"}
            onClick={() => setTab("hub")}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              tab === "hub"
                ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-100"
                : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
            }`}
          >
            skills.sh
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-4 mb-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside
          className={`flex w-full shrink-0 flex-col border-zinc-200 dark:border-zinc-800 md:w-96 md:border-r ${
            showMobileDetail ? "hidden md:flex" : "flex"
          }`}
        >
          {tab === "installed" ? (
            <>
              <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                  <input
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search skills…"
                    className="w-full rounded-lg border border-zinc-200 bg-white py-2.5 pl-10 pr-3 text-sm outline-none transition-colors placeholder:text-zinc-400 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 dark:border-zinc-700 dark:bg-zinc-900"
                  />
                </div>
                <p className="mt-2 px-1 text-[11px] text-zinc-500 dark:text-zinc-400">
                  Ctrl+click to multi-select · Shift+click for range
                </p>
                {checkedSkillNames.size > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-violet-500/20 bg-violet-50/70 px-3 py-2 dark:border-violet-500/30 dark:bg-violet-950/20">
                    <span className="text-xs font-medium text-violet-800 dark:text-violet-200">
                      {checkedSkillNames.size} selected
                    </span>
                    <div className="ml-auto flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        disabled={bulkActionPending !== null}
                        onClick={() => void bulkEnableSkills(checkedSkillList)}
                        className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-[11px] font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
                      >
                        {bulkActionPending === "enable" ? (
                          <Loader2 className="inline h-3 w-3 animate-spin" />
                        ) : (
                          "Enable"
                        )}
                      </button>
                      <button
                        type="button"
                        disabled={bulkActionPending !== null}
                        onClick={() => void bulkDisableSkills(checkedSkillList)}
                        className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-[11px] font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
                      >
                        {bulkActionPending === "disable" ? (
                          <Loader2 className="inline h-3 w-3 animate-spin" />
                        ) : (
                          "Disable"
                        )}
                      </button>
                      <button
                        type="button"
                        disabled={
                          bulkActionPending !== null || selectedDeletableCount === 0
                        }
                        onClick={() => setBulkDeleteConfirmOpen(true)}
                        className="rounded-md border border-rose-500/30 bg-white px-2.5 py-1 text-[11px] font-medium text-rose-700 transition-colors hover:bg-rose-500/10 disabled:opacity-50 dark:bg-zinc-900 dark:text-rose-300"
                      >
                        Delete
                      </button>
                      <button
                        type="button"
                        disabled={bulkActionPending !== null}
                        onClick={clearCheckedSkills}
                        className="rounded-md px-2 py-1 text-[11px] font-medium text-zinc-500 transition-colors hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                )}
              </div>
              <div className="flex-1 overflow-y-auto px-3 py-3">
                {loading && skillsByCategory.length === 0 ? (
                  <div className="flex justify-center p-12">
                    <Loader2 className="h-6 w-6 animate-spin text-violet-500" />
                  </div>
                ) : skillsByCategory.length === 0 ? (
                  <div className="flex flex-col items-center px-4 py-16 text-center">
                    <Search className="mb-3 h-8 w-8 text-zinc-300 dark:text-zinc-600" />
                    <p className="text-sm font-medium text-zinc-600 dark:text-zinc-400">
                      {searchQuery.trim()
                        ? "No skills match your search"
                        : "No skills installed yet"}
                    </p>
                    <p className="mt-1 text-xs text-zinc-500">
                      {searchQuery.trim()
                        ? "Try a different keyword"
                        : "Use the skills.sh tab to browse and install skills"}
                    </p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {skillsByCategory.map(([cat, items]) => {
                      const collapsed = collapsedCats.has(cat);
                      const enabledCount = items.filter((s) => !s.disabled).length;
                      return (
                        <section key={cat}>
                          <button
                            type="button"
                            onClick={() => toggleCategory(cat)}
                            className="mb-2 flex w-full items-center gap-2 rounded-md px-1 py-1 text-left transition-colors outline-none focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 hover:bg-zinc-100 dark:hover:bg-zinc-900"
                          >
                            {collapsed ? (
                              <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" />
                            ) : (
                              <ChevronDown className="h-4 w-4 shrink-0 text-zinc-400" />
                            )}
                            <span className="text-xs font-semibold tracking-wide text-zinc-600 uppercase dark:text-zinc-400">
                              {formatCategoryLabel(cat)}
                            </span>
                            <span className="rounded-full bg-zinc-200/80 px-2 py-0.5 text-[10px] font-medium tabular-nums text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                              {enabledCount}/{items.length}
                            </span>
                          </button>
                          {!collapsed && (
                            <ul className="space-y-2">
                              {items.map((skill) => {
                                const enabled = !skill.disabled;
                                const isChecked = checkedSkillNames.has(skill.name);
                                const isDetailFocused =
                                  selectedName === skill.name && checkedSkillNames.size <= 1;
                                return (
                                  <li key={skill.name}>
                                    <div
                                      className={`group rounded-xl border transition-colors ${
                                        isChecked
                                          ? "border-violet-500/40 bg-violet-50/80 dark:border-violet-500/30 dark:bg-violet-950/30"
                                          : isDetailFocused
                                            ? "border-violet-500/40 bg-violet-50/80 dark:border-violet-500/30 dark:bg-violet-950/30"
                                            : "border-zinc-200/80 bg-white hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900/40 dark:hover:border-zinc-700"
                                      } ${skill.disabled ? "opacity-70" : ""}`}
                                    >
                                      <div className="flex items-start gap-3 p-3">
                                        <button
                                          type="button"
                                          onClick={(event) => handleSkillListClick(skill.name, event)}
                                          className="min-w-0 flex-1 rounded-lg text-left outline-none focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
                                        >
                                          <div className="flex flex-wrap items-center gap-2">
                                            <div className="font-mono text-sm font-medium leading-snug text-zinc-900 dark:text-zinc-100">
                                              {skill.name}
                                            </div>
                                            {skill.source === "external" && (
                                              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-amber-800 uppercase dark:bg-amber-950/50 dark:text-amber-300">
                                                External
                                              </span>
                                            )}
                                            {skill.source === "default" && (
                                              <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-zinc-600 uppercase dark:bg-zinc-800 dark:text-zinc-400">
                                                Default
                                              </span>
                                            )}
                                          </div>
                                          {skill.description && (
                                            <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
                                              {skill.description}
                                            </p>
                                          )}
                                        </button>
                                        <SkillToggle
                                          enabled={enabled}
                                          pending={togglePending === skill.name}
                                          onToggle={() => void handleToggle(skill.name, enabled)}
                                        />
                                      </div>
                                    </div>
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                        </section>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          ) : (
            <>
              <form
                className="flex gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800"
                onSubmit={(e) => {
                  e.preventDefault();
                  void runHubSearch();
                }}
              >
                <div className="relative min-w-0 flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                  <input
                    type="search"
                    value={hubQuery}
                    onChange={(e) => setHubQuery(e.target.value)}
                    placeholder="Skill name or repo (e.g. anthropics/skills)…"
                    className="w-full rounded-lg border border-zinc-200 bg-white py-2.5 pl-10 pr-3 text-sm outline-none transition-colors focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 dark:border-zinc-700 dark:bg-zinc-900"
                  />
                </div>
                <button
                  type="submit"
                  disabled={hubLoading || !hubQuery.trim()}
                  className="shrink-0 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-50"
                >
                  {hubLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
                </button>
              </form>
              <div className="flex-1 overflow-y-auto px-3 py-3">
                {hubError && (
                  <p className="mb-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-600 dark:text-rose-400">
                    {hubError}
                  </p>
                )}
                {hubResults.length === 0 && !hubLoading && !hubError && (
                  <div className="flex flex-col items-center px-4 py-16 text-center">
                    <Download className="mb-3 h-8 w-8 text-zinc-300 dark:text-zinc-600" />
                    <p className="text-sm font-medium text-zinc-600 dark:text-zinc-400">
                      Discover skills on skills.sh
                    </p>
                    <p className="mt-1 text-xs text-zinc-500">
                      Search by skill name, or enter a repo like{" "}
                      <span className="font-mono text-zinc-600 dark:text-zinc-300">
                        anthropics/skills
                      </span>{" "}
                      to browse a group. Also on{" "}
                      <a
                        href="https://skills.sh"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-violet-600 hover:underline dark:text-violet-400"
                      >
                        skills.sh
                      </a>
                    </p>
                  </div>
                )}
                {showGroupedHub ? (
                  <div className="space-y-3">
                    {hubGroups.map((group) => renderHubGroup(group))}
                  </div>
                ) : (
                  <ul className="space-y-2">
                    {hubResults.map((row) => renderHubSkillRow(row))}
                  </ul>
                )}
              </div>
            </>
          )}
        </aside>

        <section
          className={`min-w-0 flex-1 overflow-y-auto ${
            showMobileDetail ? "flex" : "hidden md:flex md:flex-col"
          }`}
        >
          {showMobileDetail && (
            <div className="flex shrink-0 items-center gap-2 border-b border-zinc-200 px-4 py-2 md:hidden dark:border-zinc-800">
              <button
                type="button"
                onClick={
                  formMode
                    ? cancelSkillForm
                    : selectedHub
                      ? clearHubSelection
                      : clearSelection
                }
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              >
                <ArrowLeft className="h-4 w-4" />
                All skills
              </button>
            </div>
          )}
          <div className="flex-1 p-4 md:p-6">
            {formMode ? (
              <article>
                <h2 className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                  {formMode === "create" ? "New skill" : `Edit · ${selectedName}`}
                </h2>
                <div className="mt-4">{renderSkillForm()}</div>
              </article>
            ) : selectedHub ? (
              hubDetailLoading ? (
                <div className="flex justify-center p-12">
                  <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
                </div>
              ) : hubDetailError ? (
                <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-600 dark:text-rose-400">
                  {hubDetailError}
                </p>
              ) : (
                <article>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                        {selectedHub.name}
                      </h2>
                      {selectedHub.description && (
                        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                          {selectedHub.description}
                        </p>
                      )}
                      <p className="mt-2 truncate font-mono text-[11px] text-zinc-400">
                        {selectedHub.identifier}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={installPending === selectedHub.identifier}
                      onClick={() => void installAndShow(selectedHub.identifier)}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-50"
                    >
                      {installPending === selectedHub.identifier ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Download className="h-3.5 w-3.5" />
                      )}
                      Install
                    </button>
                  </div>
                  <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
                    <SkillMarkdownView content={hubDetailContent ?? ""} />
                  </div>
                </article>
              )
            ) : !selectedName ? (
              <div className="flex h-full min-h-[240px] flex-col items-center justify-center text-center text-zinc-500">
                <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-100 dark:bg-zinc-900">
                  <Layers className="h-7 w-7 opacity-40" />
                </div>
                <p className="text-sm font-medium text-zinc-600 dark:text-zinc-400">
                  Select a skill to view its contents
                </p>
                <p className="mt-1 max-w-xs text-xs text-zinc-500">
                  {tab === "hub"
                    ? "Tap a hub result to preview SKILL.md before installing"
                    : "Tap a skill name to read its instructions and linked files"}
                </p>
              </div>
            ) : detailLoading ? (
              <div className="flex justify-center p-12">
                <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
              </div>
            ) : detailError ? (
              <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-600 dark:text-rose-400">
                {detailError}
              </p>
            ) : (
              <article>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-mono text-lg font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                        {selectedName}
                      </h2>
                      {selectedSkill?.source === "external" && (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-amber-800 uppercase dark:bg-amber-950/50 dark:text-amber-300">
                          External
                        </span>
                      )}
                      {selectedSkill?.source === "default" && (
                        <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-zinc-600 uppercase dark:bg-zinc-800 dark:text-zinc-400">
                          Default
                        </span>
                      )}
                    </div>
                    {selectedSkill?.source === "external" && (
                      <p className="mt-1 text-xs text-zinc-500">
                        Installed from an external directory (e.g. npx skills). You can disable or
                        delete it here; files are removed from the configured external skills path.
                      </p>
                    )}
                    {selectedSkill?.source === "default" && !isAdmin && (
                      <p className="mt-1 text-xs text-zinc-500">
                        Default skills are read-only. Create your own skill to customize behavior.
                      </p>
                    )}
                    {selectedSkill?.source === "default" && isAdmin && (
                      <p className="mt-1 text-xs text-zinc-500">
                        Inherited default skill. Administrators can edit or delete it.
                      </p>
                    )}
                  </div>
                  {skillIsMutable(selectedSkill) && (
                    <div className="flex shrink-0 gap-2">
                      <button
                        type="button"
                        onClick={startEditSkill}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        Edit
                      </button>
                      <button
                        type="button"
                        disabled={deletePending}
                        onClick={() => setDeleteConfirmOpen(true)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/30 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-500/10 disabled:opacity-50 dark:text-rose-300"
                      >
                        {deletePending ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                        Delete
                      </button>
                    </div>
                  )}
                </div>
                <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
                  <SkillMarkdownView content={detailContent ?? ""} />
                </div>
              </article>
            )}
          </div>
        </section>
      </div>

      <ConfirmModal
        isOpen={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
        onConfirm={async () => {
          const ok = await removeSelectedSkill();
          if (ok) setDeleteConfirmOpen(false);
        }}
        title="Delete skill"
        message={`Delete skill "${selectedName ?? ""}"? This cannot be undone.`}
        confirmText="Delete"
        type="danger"
      />
      <ConfirmModal
        isOpen={bulkDeleteConfirmOpen}
        onClose={() => setBulkDeleteConfirmOpen(false)}
        onConfirm={async () => {
          const result = await bulkDeleteSkills(checkedSkillList);
          if (
            result.deletedCount > 0 ||
            result.skippedCount > 0 ||
            result.failedCount > 0
          ) {
            setBulkDeleteConfirmOpen(false);
            if (result.deletedCount > 0) clearCheckedSkills();
          }
        }}
        title="Delete selected skills"
        message={
          isAdmin
            ? `Delete ${selectedDeletableCount} skill${selectedDeletableCount === 1 ? "" : "s"}? This cannot be undone.`
            : `Delete ${selectedDeletableCount} skill${selectedDeletableCount === 1 ? "" : "s"}? Default skills are skipped. This cannot be undone.`
        }
        confirmText="Delete"
        type="danger"
      />
    </div>
  );
};
