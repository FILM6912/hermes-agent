import React, { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  Brain,
  Loader2,
  Pencil,
  Save,
  Sparkles,
  User,
  X,
} from "lucide-react";
import { getAuthStatus, type AuthStatus } from "@/features/auth/services/authService";
import {
  canAccessAgentSoul,
  fetchMemory,
  fetchNotesItem,
  fetchNotesSources,
  memorySectionContent,
  memorySectionMtime,
  searchNotes,
  writeMemory,
  type MemoryPayload,
  type MemorySection,
  type NotesItemResponse,
  type NotesSearchResult,
  type NotesSourcesResponse,
} from "./memoryApi";

type PanelSection = MemorySection | "external_notes";

const SECTIONS: Array<{
  key: PanelSection;
  label: string;
  empty: string;
  icon: React.ReactNode;
}> = [
  { key: "memory", label: "My notes", empty: "No notes yet", icon: <Brain className="h-4 w-4" /> },
  { key: "user", label: "User profile", empty: "No profile yet", icon: <User className="h-4 w-4" /> },
  { key: "soul", label: "Agent Soul", empty: "No soul file yet", icon: <Sparkles className="h-4 w-4" /> },
  {
    key: "external_notes",
    label: "External notes",
    empty: "No external sources configured",
    icon: <BookOpen className="h-4 w-4" />,
  },
];

interface MemoryPanelProps {
  onBack: () => void;
}

function formatMtime(ts: number | null): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString();
}

export const MemoryPanel: React.FC<MemoryPanelProps> = ({ onBack }) => {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [data, setData] = useState<MemoryPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<PanelSection>("memory");
  const [mode, setMode] = useState<"read" | "edit">("read");
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [notesSources, setNotesSources] = useState<NotesSourcesResponse | null>(null);
  const [notesSource, setNotesSource] = useState("joplin");
  const [notesQuery, setNotesQuery] = useState("");
  const [notesResults, setNotesResults] = useState<NotesSearchResult[]>([]);
  const [notesSearchError, setNotesSearchError] = useState("");
  const [notesSearching, setNotesSearching] = useState(false);
  const [notesPreview, setNotesPreview] = useState<NotesItemResponse["note"] | null>(null);

  const canSoul = canAccessAgentSoul(auth);

  const loadMemory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mem, status] = await Promise.all([fetchMemory(), getAuthStatus()]);
      setAuth(status);
      setData(mem);
      if (section === "external_notes" && !mem.external_notes_enabled) {
        setSection("memory");
      }
      if (section === "soul" && !canAccessAgentSoul(status)) {
        setSection("memory");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load memory");
    } finally {
      setLoading(false);
    }
  }, [section]);

  useEffect(() => {
    void loadMemory();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadNotes = useCallback(async () => {
    try {
      const sources = await fetchNotesSources();
      setNotesSources(sources);
      const first = sources.sources?.[0]?.name;
      if (first) setNotesSource(first);
    } catch (err) {
      setNotesSources({
        enabled: false,
        sources: [],
        error: err instanceof Error ? err.message : "Failed to load note sources",
      });
    }
  }, []);

  useEffect(() => {
    if (section === "external_notes" && data?.external_notes_enabled) {
      void loadNotes();
    }
  }, [section, data?.external_notes_enabled, loadNotes]);

  const visibleSections = SECTIONS.filter((s) => {
    if (s.key === "soul" && !canSoul) return false;
    if (s.key === "external_notes" && !data?.external_notes_enabled) return false;
    return true;
  });

  const startEdit = () => {
    if (!data || section === "external_notes") return;
    setDraft(memorySectionContent(data, section as MemorySection));
    setMode("edit");
    setSaveError(null);
  };

  const cancelEdit = () => {
    setMode("read");
    setSaveError(null);
  };

  const saveEdit = async () => {
    if (section === "external_notes") return;
    setSaving(true);
    setSaveError(null);
    try {
      await writeMemory(section as MemorySection, draft);
      await loadMemory();
      setMode("read");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const runNotesSearch = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const q = notesQuery.trim();
    setNotesPreview(null);
    if (!q) {
      setNotesResults([]);
      setNotesSearchError("");
      return;
    }
    setNotesSearching(true);
    setNotesSearchError("");
    try {
      const res = await searchNotes({ source: notesSource, q, limit: 20 });
      setNotesResults(res.results ?? []);
      setNotesSearchError(res.error ?? "");
    } catch (err) {
      setNotesResults([]);
      setNotesSearchError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setNotesSearching(false);
    }
  };

  const previewNote = async (source: string, id: string) => {
    setNotesSearchError("");
    try {
      const res = await fetchNotesItem({ source, id });
      setNotesPreview(res.note ?? null);
      if (res.error) setNotesSearchError(res.error);
    } catch (err) {
      setNotesPreview(null);
      setNotesSearchError(err instanceof Error ? err.message : "Preview failed");
    }
  };

  const meta = SECTIONS.find((s) => s.key === section) ?? SECTIONS[0];
  const content =
    data && section !== "external_notes"
      ? memorySectionContent(data, section as MemorySection)
      : "";
  const mtime =
    data && section !== "external_notes"
      ? memorySectionMtime(data, section as MemorySection)
      : null;

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
        <Brain className="h-5 w-5 text-violet-500" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">Memory</h1>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
            Notes, user profile, and agent soul
          </p>
        </div>
        {mode === "read" && section !== "external_notes" && (
          <button
            type="button"
            onClick={startEdit}
            disabled={loading || !data}
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            <Pencil className="h-4 w-4" />
            Edit
          </button>
        )}
        {mode === "edit" && (
          <>
            <button
              type="button"
              onClick={cancelEdit}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm dark:border-zinc-700"
            >
              <X className="h-4 w-4" />
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void saveEdit()}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save
            </button>
          </>
        )}
      </header>

      <div className="flex min-h-0 flex-1">
        <nav className="flex w-52 shrink-0 flex-col gap-1 border-r border-zinc-200 p-3 dark:border-zinc-800">
          {visibleSections.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => {
                setSection(s.key);
                setMode("read");
                setSaveError(null);
              }}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                section === s.key
                  ? "bg-violet-500/15 font-medium text-violet-700 dark:text-violet-300"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              }`}
            >
              {s.icon}
              {s.label}
            </button>
          ))}
        </nav>

        <main className="min-h-0 flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
            </div>
          )}
          {error && !loading && (
            <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
              {error}
            </p>
          )}

          {!loading && !error && section !== "external_notes" && (
            <div className="mx-auto max-w-3xl">
              <h2 className="mb-1 text-base font-semibold">{meta.label}</h2>
              {mtime ? (
                <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">
                  Updated {formatMtime(mtime)}
                </p>
              ) : (
                <div className="mb-4" />
              )}
              {saveError && (
                <p className="mb-3 text-sm text-rose-600 dark:text-rose-400">{saveError}</p>
              )}
              {mode === "edit" ? (
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={22}
                  spellCheck={false}
                  className="w-full rounded-xl border border-zinc-200 bg-white p-3 font-mono text-sm leading-relaxed dark:border-zinc-700 dark:bg-zinc-900"
                />
              ) : content ? (
                <pre className="whitespace-pre-wrap rounded-xl border border-zinc-200 bg-white p-4 font-mono text-sm leading-relaxed dark:border-zinc-700 dark:bg-zinc-900">
                  {content}
                </pre>
              ) : (
                <p className="text-sm text-zinc-500 dark:text-zinc-400">{meta.empty}</p>
              )}
            </div>
          )}

          {!loading && !error && section === "external_notes" && (
            <div className="mx-auto max-w-3xl space-y-4">
              <h2 className="text-base font-semibold">{meta.label}</h2>
              {notesSources?.automatic_recall_unchanged !== false && (
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Automatic session recall is unchanged — this drawer is read-only search and preview.
                </p>
              )}

              <form
                onSubmit={(e) => void runNotesSearch(e)}
                className="flex flex-wrap items-center gap-2 rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-700 dark:bg-zinc-900"
              >
                <select
                  value={notesSource}
                  onChange={(e) => setNotesSource(e.target.value)}
                  className="rounded-lg border border-zinc-200 bg-zinc-50 px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-800"
                >
                  {(notesSources?.sources ?? []).map((src) => (
                    <option key={src.name} value={src.name}>
                      {src.label || src.name}
                    </option>
                  ))}
                </select>
                <input
                  type="search"
                  value={notesQuery}
                  onChange={(e) => setNotesQuery(e.target.value)}
                  placeholder="Search notes…"
                  className="min-w-[12rem] flex-1 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-800"
                />
                <button
                  type="submit"
                  disabled={notesSearching}
                  className="rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
                >
                  {notesSearching ? "Searching…" : "Search"}
                </button>
              </form>

              {notesSearchError && (
                <p className="text-sm text-rose-600 dark:text-rose-400">{notesSearchError}</p>
              )}

              {notesResults.length > 0 ? (
                <ul className="space-y-2">
                  {notesResults.map((note) => (
                    <li key={`${note.source}-${note.id}`}>
                      <button
                        type="button"
                        onClick={() =>
                          void previewNote(note.source || notesSource, String(note.id ?? ""))
                        }
                        className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-left text-sm hover:border-violet-400 dark:border-zinc-700 dark:bg-zinc-900"
                      >
                        <div className="font-medium">{note.title || "Untitled"}</div>
                        {note.snippet && (
                          <div className="mt-1 text-xs text-zinc-500 line-clamp-2 dark:text-zinc-400">
                            {note.snippet}
                          </div>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                notesQuery.trim() &&
                !notesSearching && (
                  <p className="text-sm text-zinc-500">No results for this query.</p>
                )
              )}

              {notesPreview && (
                <article className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
                  <h3 className="mb-2 font-semibold">{notesPreview.title || "Untitled"}</h3>
                  <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed">
                    {notesPreview.body || ""}
                  </pre>
                </article>
              )}

              {(notesSources?.sources ?? []).map((src) => (
                <section
                  key={src.name}
                  className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <strong>{src.label || src.name}</strong>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        src.active
                          ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                          : "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400"
                      }`}
                    >
                      {src.active ? "Active" : src.status || "Configured"}
                    </span>
                  </div>
                  {src.tools && src.tools.length > 0 ? (
                    <ul className="list-inside list-disc text-sm text-zinc-600 dark:text-zinc-400">
                      {src.tools.map((tool) => (
                        <li key={tool.name}>
                          <span className="font-medium text-zinc-800 dark:text-zinc-200">
                            {tool.name}
                          </span>
                          {tool.description ? ` — ${tool.description}` : ""}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-zinc-500">No tools listed for this source.</p>
                  )}
                </section>
              ))}

              {!notesSources?.sources?.length && (
                <p className="text-sm text-zinc-500">{meta.empty}</p>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
};
