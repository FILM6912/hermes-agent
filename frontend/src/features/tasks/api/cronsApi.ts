import { fetchJson } from "@/lib/api";
import type {
  CronDeliveryOption,
  CronFormValues,
  CronJob,
  CronJobsResponse,
  CronMutationResponse,
} from "../types";

/** GET /api/v1/crons */
export async function listCrons(): Promise<CronJobsResponse> {
  return fetchJson<CronJobsResponse>("/crons");
}

/** GET /api/v1/crons/delivery-options */
export async function fetchCronDeliveryOptions(): Promise<{ platforms: CronDeliveryOption[] }> {
  return fetchJson("/crons/delivery-options");
}

function formToCreateBody(values: CronFormValues): Record<string, unknown> {
  const body: Record<string, unknown> = {
    schedule: values.schedule.trim(),
    prompt: values.prompt.trim(),
    deliver: values.deliver || "local",
    toast_notifications: values.toast_notifications,
  };
  const name = values.name.trim();
  if (name) body.name = name;
  const profile = values.profile.trim();
  if (profile) body.profile = profile;
  return body;
}

function formToUpdateBody(jobId: string, values: CronFormValues): Record<string, unknown> {
  const body: Record<string, unknown> = {
    job_id: jobId,
    schedule: values.schedule.trim(),
    toast_notifications: values.toast_notifications,
  };
  const name = values.name.trim();
  if (name) body.name = name;
  body.deliver = values.deliver || "local";
  body.profile = values.profile.trim() || null;
  body.prompt = values.prompt.trim();
  return body;
}

/** POST /api/v1/crons/create */
export async function createCron(values: CronFormValues): Promise<CronMutationResponse> {
  return fetchJson<CronMutationResponse>("/crons/create", {
    method: "POST",
    body: formToCreateBody(values),
  });
}

/** POST /api/v1/crons/update */
export async function updateCron(jobId: string, values: CronFormValues): Promise<CronMutationResponse> {
  return fetchJson<CronMutationResponse>("/crons/update", {
    method: "POST",
    body: formToUpdateBody(jobId, values),
  });
}

/** POST /api/v1/crons/delete */
export async function deleteCron(jobId: string): Promise<CronMutationResponse> {
  return fetchJson<CronMutationResponse>("/crons/delete", {
    method: "POST",
    body: { job_id: jobId },
  });
}

/** POST /api/v1/crons/run */
export async function runCron(jobId: string): Promise<CronMutationResponse> {
  return fetchJson<CronMutationResponse>("/crons/run", {
    method: "POST",
    body: { job_id: jobId },
  });
}

/** POST /api/v1/crons/pause */
export async function pauseCron(jobId: string): Promise<CronMutationResponse> {
  return fetchJson<CronMutationResponse>("/crons/pause", {
    method: "POST",
    body: { job_id: jobId },
  });
}

/** POST /api/v1/crons/resume */
export async function resumeCron(jobId: string): Promise<CronMutationResponse> {
  return fetchJson<CronMutationResponse>("/crons/resume", {
    method: "POST",
    body: { job_id: jobId },
  });
}

export function cronJobToFormValues(job: CronJob): CronFormValues {
  let schedule = "";
  if (typeof job.schedule === "string") {
    schedule = job.schedule;
  } else if (job.schedule && typeof job.schedule === "object") {
    schedule = JSON.stringify(job.schedule);
  }
  return {
    name: job.name ?? "",
    schedule,
    prompt: job.prompt ?? "",
    deliver: job.deliver ?? "local",
    profile: job.profile ?? "",
    toast_notifications: job.toast_notifications !== false,
  };
}

export function cronStatusLabel(job: CronJob): { label: string; tone: "ok" | "warn" | "err" | "muted" } {
  if (job.state === "paused") {
    return { label: "Paused", tone: "warn" };
  }
  if (job.enabled === false) {
    return { label: "Disabled", tone: "muted" };
  }
  if (job.last_status === "error") {
    return { label: "Error", tone: "err" };
  }
  return { label: "Active", tone: "ok" };
}

export function formatSchedule(schedule: CronJob["schedule"]): string {
  if (typeof schedule === "string") return schedule;
  if (schedule && typeof schedule === "object") {
    return JSON.stringify(schedule);
  }
  return "—";
}
