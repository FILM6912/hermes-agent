import { useCallback, useEffect, useState } from "react";
import { HermesApiError } from "@/lib/api";
import { listProfiles } from "@/services/hermes/profiles";
import {
  createCron,
  cronJobToFormValues,
  deleteCron,
  fetchCronDeliveryOptions,
  listCrons,
  pauseCron,
  resumeCron,
  runCron,
  updateCron,
} from "../api/cronsApi";
import type { CronFormMode, CronFormValues, CronJob } from "../types";

const EMPTY_FORM: CronFormValues = {
  name: "",
  schedule: "",
  prompt: "",
  deliver: "local",
  profile: "",
  toast_notifications: true,
};

export function useCrons() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<CronFormMode>("view");
  const [formValues, setFormValues] = useState<CronFormValues>(EMPTY_FORM);
  const [profiles, setProfiles] = useState<string[]>([]);
  const [deliveryOptions, setDeliveryOptions] = useState<{ value: string; label: string }[]>([]);
  const [actionPending, setActionPending] = useState(false);

  const selectedJob = jobs.find((j) => j.id === selectedId) ?? null;

  const loadJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCrons();
      setJobs(data.jobs ?? []);
    } catch (err) {
      const message =
        err instanceof HermesApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to load scheduled jobs";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
    void listProfiles()
      .then((data) => setProfiles(data.profiles.map((p) => p.name)))
      .catch(() => setProfiles([]));
    void fetchCronDeliveryOptions()
      .then((data) => setDeliveryOptions(data.platforms ?? []))
      .catch(() => setDeliveryOptions([{ value: "local", label: "Local" }]));
  }, [loadJobs]);

  const selectJob = useCallback((job: CronJob) => {
    setSelectedId(job.id);
    setFormMode("view");
    setFormValues(cronJobToFormValues(job));
  }, []);

  const openCreate = useCallback(() => {
    setSelectedId(null);
    setFormMode("create");
    setFormValues(EMPTY_FORM);
  }, []);

  const openEdit = useCallback(() => {
    if (!selectedJob) return;
    setFormMode("edit");
    setFormValues(cronJobToFormValues(selectedJob));
  }, [selectedJob]);

  const cancelForm = useCallback(() => {
    if (selectedJob) {
      setFormMode("view");
      setFormValues(cronJobToFormValues(selectedJob));
    } else {
      setFormMode("view");
      setFormValues(EMPTY_FORM);
    }
  }, [selectedJob]);

  const saveForm = useCallback(async () => {
    if (!formValues.schedule.trim()) {
      setError("Schedule is required");
      return;
    }
    if (!selectedJob?.no_agent && !formValues.prompt.trim() && formMode === "create") {
      setError("Prompt is required");
      return;
    }
    setActionPending(true);
    setError(null);
    try {
      if (formMode === "create") {
        const res = await createCron(formValues);
        await loadJobs();
        const newId = res.job?.id;
        if (newId) setSelectedId(newId);
        setFormMode("view");
      } else if (formMode === "edit" && selectedId) {
        await updateCron(selectedId, formValues);
        await loadJobs();
        setFormMode("view");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setActionPending(false);
    }
  }, [formMode, formValues, loadJobs, selectedId, selectedJob?.no_agent]);

  const runAction = useCallback(
    async (action: "run" | "pause" | "resume" | "delete") => {
      if (!selectedId) return;
      setActionPending(true);
      setError(null);
      try {
        if (action === "run") await runCron(selectedId);
        else if (action === "pause") await pauseCron(selectedId);
        else if (action === "resume") await resumeCron(selectedId);
        else if (action === "delete") {
          await deleteCron(selectedId);
          setSelectedId(null);
          setFormMode("view");
          setFormValues(EMPTY_FORM);
        }
        await loadJobs();
      } catch (err) {
        setError(err instanceof Error ? err.message : `${action} failed`);
      } finally {
        setActionPending(false);
      }
    },
    [loadJobs, selectedId],
  );

  return {
    jobs,
    loading,
    error,
    selectedJob,
    selectedId,
    formMode,
    formValues,
    setFormValues,
    profiles,
    deliveryOptions,
    actionPending,
    loadJobs,
    selectJob,
    openCreate,
    openEdit,
    cancelForm,
    saveForm,
    runAction,
  };
}
