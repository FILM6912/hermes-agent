import { fetchJson } from "@/lib/api";

export type OnboardingSetupProvider = {
  id: string;
  label: string;
  env_var: string;
  default_model: string;
  default_base_url: string;
  requires_base_url: boolean;
  key_optional: boolean;
  models: { id: string; label: string }[];
  category: string;
  quick: boolean;
  oauth_provider: string;
  oauth_label: string;
};

export type OnboardingSetupCategory = {
  id: string;
  label: string;
  providers: string[];
};

export type OnboardingSystemStatus = {
  hermes_found: boolean;
  imports_ok: boolean;
  missing_modules?: string[];
  import_errors?: Record<string, string>;
  config_path?: string;
  config_exists?: boolean;
  env_path?: string;
  provider_configured: boolean;
  provider_ready: boolean;
  chat_ready: boolean;
  setup_state?: string;
  provider_note?: string;
  current_provider?: string | null;
  current_model?: string | null;
  current_base_url?: string | null;
};

export type OnboardingStatus = {
  completed: boolean;
  settings: {
    default_model?: string;
    default_workspace?: string;
    password_enabled?: boolean;
    bot_name?: string;
  };
  system: OnboardingSystemStatus;
  setup: {
    providers: OnboardingSetupProvider[];
    categories: OnboardingSetupCategory[];
    unsupported_note?: string;
    current_is_oauth?: boolean;
    current: {
      provider: string;
      model: string;
      base_url: string;
    };
  };
  workspaces: {
    items: { name: string; path: string }[];
    last?: string;
  };
  models?: unknown;
};

export type OnboardingProbeResult = {
  ok?: boolean;
  error?: string;
  detail?: string;
  models?: { id: string; label: string }[];
};

export type OnboardingOAuthStartResult = {
  ok?: boolean;
  flow_id?: string;
  provider?: string;
  status?: string;
  user_code?: string;
  verification_uri?: string;
  error?: string;
};

export type OnboardingOAuthPollResult = {
  status: string;
  error?: string;
  flow_id?: string;
};

export type OnboardingSetupBody = {
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
  confirm_overwrite?: boolean;
};

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  return fetchJson<OnboardingStatus>("/onboarding/status");
}

export async function postOnboardingSetup(
  body: OnboardingSetupBody,
): Promise<OnboardingStatus> {
  return fetchJson<OnboardingStatus>("/onboarding/setup", {
    method: "POST",
    body,
  });
}

export async function postOnboardingComplete(): Promise<OnboardingStatus> {
  return fetchJson<OnboardingStatus>("/onboarding/complete", {
    method: "POST",
    body: {},
  });
}

export async function postOnboardingProbe(body: {
  provider: string;
  base_url: string;
  api_key?: string;
}): Promise<OnboardingProbeResult> {
  return fetchJson<OnboardingProbeResult>("/onboarding/probe", {
    method: "POST",
    body,
  });
}

export async function postOnboardingOAuthStart(body: {
  provider: string;
}): Promise<OnboardingOAuthStartResult> {
  return fetchJson<OnboardingOAuthStartResult>("/onboarding/oauth/start", {
    method: "POST",
    body,
  });
}

export async function fetchOnboardingOAuthPoll(
  flowId: string,
): Promise<OnboardingOAuthPollResult> {
  return fetchJson<OnboardingOAuthPollResult>("/onboarding/oauth/poll", {
    query: { flow_id: flowId },
  });
}

export async function postOnboardingOAuthCancel(body: {
  flow_id: string;
  provider?: string;
}): Promise<OnboardingOAuthPollResult> {
  return fetchJson<OnboardingOAuthPollResult>("/onboarding/oauth/cancel", {
    method: "POST",
    body,
  });
}
