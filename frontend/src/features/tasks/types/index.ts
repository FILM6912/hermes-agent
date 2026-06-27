export type CronJob = {
  id: string;
  name?: string;
  schedule?: string | Record<string, unknown>;
  prompt?: string;
  deliver?: string;
  profile?: string | null;
  enabled?: boolean;
  state?: string;
  last_status?: string;
  last_run?: string | number | null;
  next_run?: string | number | null;
  no_agent?: boolean;
  toast_notifications?: boolean;
  skills?: string[];
  [key: string]: unknown;
};

export type CronJobsResponse = {
  jobs: CronJob[];
};

export type CronMutationResponse = {
  ok?: boolean;
  job?: CronJob;
  job_id?: string;
  error?: string;
};

export type CronDeliveryOption = {
  value: string;
  label: string;
};

export type CronFormValues = {
  name: string;
  schedule: string;
  prompt: string;
  deliver: string;
  profile: string;
  toast_notifications: boolean;
};

export type CronFormMode = "create" | "edit" | "view";
