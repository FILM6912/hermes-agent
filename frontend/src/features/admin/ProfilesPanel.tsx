import React, { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { Loader2, Plus, RefreshCw, Trash2, Layers, RotateCcw } from "lucide-react";
import { listPickerModels, type PickerModel } from "@/services/hermes/models";
import {
  createProfile,
  deleteProfile,
  listProfiles,
  syncProfileFromDefault,
  updateProfileModel,
  type HermesProfileSummary,
} from "./profilesApi";

function pickerIdForProfile(
  profile: HermesProfileSummary,
  models: PickerModel[],
): string {
  const model = profile.model?.trim();
  if (!model) return "";
  const provider = profile.provider?.trim() || "";
  const exact = models.find((m) => m.id === model);
  if (exact) return exact.id;
  const match = models.find(
    (m) =>
      m.id === model ||
      m.id.endsWith(`:${model}`) ||
      (provider && m.hermesProvider === provider && m.id.includes(model)),
  );
  return match?.id ?? model;
}

const PROFILE_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

export const ProfilesPanel: React.FC = () => {
  const location = useLocation();
  const focusProfile = (
    location.state as { focusProfile?: string } | null
  )?.focusProfile?.trim();
  const highlightedRef = useRef<HTMLDivElement | null>(null);
  const [profiles, setProfiles] = useState<HermesProfileSummary[]>([]);
  const [active, setActive] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [pickerModels, setPickerModels] = useState<PickerModel[]>([]);

  const loadProfiles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listProfiles();
      setProfiles(data.profiles ?? []);
      setActive(data.active ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  useEffect(() => {
    if (!focusProfile || loading) return;
    highlightedRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusProfile, loading, profiles.length]);

  useEffect(() => {
    let cancelled = false;
    void listPickerModels()
      .then((result) => {
        const models = Array.isArray(result) ? result : (result?.models ?? []);
        if (!cancelled) setPickerModels(models);
      })
      .catch(() => {
        if (!cancelled) setPickerModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const name = createName.trim();
    if (!PROFILE_NAME_RE.test(name)) {
      setFormError("Invalid profile name (lowercase letters, numbers, hyphens, underscores).");
      return;
    }
    setActionPending(true);
    try {
      await createProfile({ name });
      setCreateName("");
      setShowCreate(false);
      await loadProfiles();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionPending(false);
    }
  };

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete profile "${name}"? This cannot be undone.`)) return;
    setActionPending(true);
    setFormError(null);
    try {
      await deleteProfile(name);
      await loadProfiles();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionPending(false);
    }
  };

  const handleSyncOne = async (name: string) => {
    setActionPending(true);
    setSyncMessage(null);
    setFormError(null);
    try {
      const result = await syncProfileFromDefault(name);
      setSyncMessage(result.error ? result.error : `Synced "${name}" from default.`);
      await loadProfiles();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionPending(false);
    }
  };

  const handleModelChange = async (profileName: string, modelId: string) => {
    if (!modelId) return;
    const model = pickerModels.find((m) => m.id === modelId);
    if (!model) return;
    const currentId = pickerIdForProfile(
      profiles.find((p) => p.name === profileName) ?? { name: profileName, path: "" },
      pickerModels,
    );
    if (currentId === modelId) return;

    setActionPending(true);
    setFormError(null);
    setSyncMessage(null);
    try {
      await updateProfileModel({
        name: profileName,
        default_model: model.id,
        model_provider: model.hermesProvider ?? null,
      });
      setSyncMessage(`Updated default model for "${profileName}".`);
      await loadProfiles();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionPending(false);
    }
  };

  const handleSyncAll = async () => {
    setActionPending(true);
    setSyncMessage(null);
    setFormError(null);
    try {
      await syncProfileFromDefault();
      setSyncMessage("Synced all profiles from default.");
      await loadProfiles();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionPending(false);
    }
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Create and manage Hermes agent profiles. Active profile:{" "}
          <span className="font-mono text-zinc-700 dark:text-zinc-300">{active || "—"}</span>
          . Sync copies or updates skills and MCP servers from the default profile,
          overwrites SOUL.md, replaces the full default model stack and auth.json,
          merges other missing config, and clears each profile's model-catalog cache.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
          >
            <Plus className="h-4 w-4" />
            New profile
          </button>
          <button
            type="button"
            onClick={() => void handleSyncAll()}
            disabled={actionPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm dark:border-zinc-700"
          >
            <RotateCcw className="h-4 w-4" />
            Sync all
          </button>
          <button
            type="button"
            onClick={() => void loadProfiles()}
            disabled={loading}
            className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            aria-label="Refresh profiles"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}
      {formError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {formError}
        </div>
      )}
      {syncMessage && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">
          {syncMessage}
        </div>
      )}

      {showCreate && (
        <form
          onSubmit={handleCreate}
          className="flex flex-wrap items-end gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-[#121212]"
        >
          <label className="min-w-[200px] flex-1 space-y-1.5">
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Profile name</span>
            <input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              placeholder="my-profile"
              required
            />
          </label>
          <button
            type="submit"
            disabled={actionPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
          >
            Create
          </button>
        </form>
      )}

      <div className="space-y-3">
        {loading && profiles.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading profiles…
          </div>
        ) : profiles.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-sm text-zinc-500">
            <Layers className="h-8 w-8 opacity-40" />
            No profiles found.
          </div>
        ) : (
          profiles.map((profile) => (
            <div
              key={profile.name}
              id={`profile-row-${profile.name}`}
              ref={profile.name === focusProfile ? highlightedRef : undefined}
              className={`rounded-xl border bg-white p-4 dark:bg-[#121212] ${
                profile.name === focusProfile
                  ? "border-indigo-500 ring-2 ring-indigo-500/30"
                  : "border-zinc-200 dark:border-zinc-800"
              }`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-medium text-zinc-900 dark:text-zinc-100">
                      {profile.name}
                    </span>
                    {profile.is_active && (
                      <span className="rounded-full bg-indigo-500/15 px-2 py-0.5 text-xs text-indigo-600 dark:text-indigo-300">
                        active
                      </span>
                    )}
                    {profile.is_default && (
                      <span className="rounded-full bg-zinc-500/15 px-2 py-0.5 text-xs text-zinc-600 dark:text-zinc-400">
                        default
                      </span>
                    )}
                  </div>
                  <div className="mt-1 text-xs text-zinc-500">
                    {profile.provider && profile.model
                      ? `${profile.provider} · ${profile.model}`
                      : profile.path}
                    {profile.skill_count != null ? ` · ${profile.skill_count} skills` : ""}
                  </div>
                  <label className="mt-3 block max-w-md space-y-1">
                    <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                      Default model
                    </span>
                    <select
                      value={pickerIdForProfile(profile, pickerModels)}
                      disabled={actionPending || pickerModels.length === 0}
                      onChange={(e) => void handleModelChange(profile.name, e.target.value)}
                      className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    >
                      <option value="">
                        {pickerModels.length === 0 ? "No models available" : "Select model…"}
                      </option>
                      {pickerModels.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.name} — {model.desc}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="flex items-center gap-2">
                  {!profile.is_default && (
                    <>
                      <button
                        type="button"
                        onClick={() => void handleSyncOne(profile.name)}
                        disabled={actionPending}
                        className="rounded-lg border border-zinc-200 px-2.5 py-1 text-xs dark:border-zinc-700"
                      >
                        Sync
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleDelete(profile.name)}
                        disabled={actionPending || profile.is_active}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 px-2.5 py-1 text-xs text-rose-600 disabled:opacity-40 dark:text-rose-400"
                        title={profile.is_active ? "Cannot delete active profile" : undefined}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
