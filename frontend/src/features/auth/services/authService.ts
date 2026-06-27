import {
  fetchJson,
  getAccessToken,
  HermesApiError,
  setAccessToken,
  setCsrfToken,
} from "@/lib/api";
import type { RolePermissions } from "@/features/admin/rolesApi";

export interface AuthStatus {
  auth_enabled: boolean;
  logged_in: boolean;
  user_id?: string | null;
  email?: string | null;
  display_name?: string | null;
  department?: string | null;
  position?: string | null;
  role?: string | null;
  permissions?: RolePermissions;
  multi_user: boolean;
  profile_name?: string | null;
  profile_names?: string[];
  password_auth_enabled: boolean;
  passwordless_enabled: boolean;
  passkeys_enabled: boolean;
  passkeys_count: number;
  passkey_feature_flag: boolean;
  csrf_token?: string;
  csrfToken?: string;
}

export interface AccountProfile {
  email?: string | null;
  display_name?: string | null;
  department?: string | null;
  position?: string | null;
  role?: string | null;
  profile_name?: string | null;
  profile_names?: string[];
  multi_user: boolean;
}

export interface AuthLoginResponse {
  ok?: boolean;
  error?: string;
  message?: string;
  user_id?: string;
  email?: string;
  display_name?: string | null;
  department?: string | null;
  position?: string | null;
  role?: string;
  profile_name?: string | null;
  csrf_token?: string;
  csrfToken?: string;
  access_token?: string;
  token_type?: string;
}

export interface AuthLogoutResponse {
  ok?: boolean;
  error?: string;
}

export interface LoginParams {
  password: string;
  email?: string;
}

function csrfFromPayload(data: {
  csrf_token?: string;
  csrfToken?: string;
}): string | undefined {
  const token = data.csrf_token ?? data.csrfToken;
  return typeof token === "string" && token.trim() ? token.trim() : undefined;
}

function syncCsrfFromPayload(data: { csrf_token?: string; csrfToken?: string }): void {
  const token = csrfFromPayload(data);
  if (token) {
    setCsrfToken(token);
  }
}

function syncAccessTokenFromPayload(data: { access_token?: string }): void {
  const token = typeof data.access_token === "string" ? data.access_token.trim() : "";
  if (token) {
    setAccessToken(token);
  }
}

async function syncCsrfAfterLogin(data: AuthLoginResponse): Promise<void> {
  syncCsrfFromPayload(data);
  syncAccessTokenFromPayload(data);
  if (csrfFromPayload(data)) {
    return;
  }
  await getAuthStatus();
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const status = await fetchJson<AuthStatus>("/auth/status");
  syncCsrfFromPayload(status);
  syncAccessTokenFromPayload(status);
  if (status.auth_enabled && !status.logged_in && getAccessToken()) {
    setAccessToken("");
  }
  return status;
}

/** GET /api/v1/auth/account — current user email + display name. */
export async function getAccountProfile(): Promise<AccountProfile> {
  return fetchJson<AccountProfile>("/auth/account");
}

/** PATCH /api/v1/auth/account — update display name for the signed-in user. */
export async function updateAccountProfile(payload: {
  display_name: string;
}): Promise<AccountProfile> {
  return fetchJson<AccountProfile>("/auth/account", {
    method: "PATCH",
    body: payload,
  });
}

/** Main shell when auth is off or the session cookie is valid. */
export function isShellAuthenticated(status: AuthStatus): boolean {
  return !status.auth_enabled || status.logged_in;
}

/** Optimistic auth status from a successful login response (before cookie probe). */
export function authStatusFromLogin(
  login: AuthLoginResponse,
  prev: AuthStatus | null,
): AuthStatus {
  const csrf = csrfFromPayload(login);
  return {
    auth_enabled: true,
    logged_in: true,
    user_id: login.user_id ?? login.email ?? prev?.user_id ?? null,
    email: login.email ?? prev?.email ?? null,
    display_name: login.display_name ?? prev?.display_name ?? null,
    department: login.department ?? prev?.department ?? null,
    position: login.position ?? prev?.position ?? null,
    role: login.role ?? prev?.role ?? null,
    permissions: prev?.permissions ?? {},
    multi_user: prev?.multi_user ?? true,
    password_auth_enabled: prev?.password_auth_enabled ?? true,
    passwordless_enabled: prev?.passwordless_enabled ?? false,
    passkeys_enabled: prev?.passkeys_enabled ?? false,
    passkeys_count: prev?.passkeys_count ?? 0,
    passkey_feature_flag: prev?.passkey_feature_flag ?? false,
    ...(csrf ? { csrf_token: csrf } : {}),
  };
}

export async function login(params: LoginParams): Promise<AuthLoginResponse> {
  const body: { password: string; email?: string } = {
    password: params.password,
  };
  const email = params.email?.trim();
  if (email) {
    body.email = email;
  }

  try {
    const data = await fetchJson<AuthLoginResponse>("/auth/login", {
      method: "POST",
      body,
    });
    if (!data.ok) {
      throw new Error(data.error || "Login failed");
    }
    await syncCsrfAfterLogin(data);
    return data;
  } catch (err) {
    if (err instanceof HermesApiError) {
      const payload = err.body as AuthLoginResponse | undefined;
      throw new Error(payload?.error || err.message);
    }
    throw err;
  }
}

export async function logout(): Promise<AuthLogoutResponse> {
  const response = await fetchJson<AuthLogoutResponse>("/auth/logout", {
    method: "POST",
    body: {},
  });
  setCsrfToken("");
  setAccessToken("");
  return response;
}

/** Base64url → bytes (WebAuthn wire format from Hermes JSON). */
function b64uToBytes(s: string): Uint8Array {
  let normalized = String(s || "").replace(/-/g, "+").replace(/_/g, "/");
  while (normalized.length % 4) normalized += "=";
  const bin = atob(normalized);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToB64u(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

type PasskeyOptionsResponse = {
  publicKey?: PublicKeyCredentialRequestOptions & {
    challenge: string;
    allowCredentials?: Array<{
      id: string;
      type: PublicKeyCredentialType;
      transports?: AuthenticatorTransport[];
    }>;
  };
  error?: string;
};

type PasskeyAssertionPayload = {
  id: string;
  rawId: string;
  type: string;
  response: {
    authenticatorData: string;
    clientDataJSON: string;
    signature: string;
    userHandle: string | null;
  };
};

function decodeRequestOptions(
  pk: NonNullable<PasskeyOptionsResponse["publicKey"]>,
): PublicKeyCredentialRequestOptions {
  const challenge = b64uToBytes(pk.challenge as unknown as string);
  const allowCredentials = pk.allowCredentials?.map((cred) => ({
    ...cred,
    id: b64uToBytes(cred.id as unknown as string),
  }));
  return {
    ...pk,
    challenge,
    allowCredentials,
  } as PublicKeyCredentialRequestOptions;
}

function encodeAssertion(cred: PublicKeyCredential): PasskeyAssertionPayload {
  const response = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: bytesToB64u(cred.rawId),
    type: cred.type,
    response: {
      authenticatorData: bytesToB64u(response.authenticatorData),
      clientDataJSON: bytesToB64u(response.clientDataJSON),
      signature: bytesToB64u(response.signature),
      userHandle: response.userHandle ? bytesToB64u(response.userHandle) : null,
    },
  };
}

export async function getPasskeyLoginOptions(): Promise<PublicKeyCredentialRequestOptions> {
  const data = await fetchJson<PasskeyOptionsResponse>("/auth/passkey/options", {
    method: "POST",
    body: {},
  });
  if (!data.publicKey) {
    throw new Error(data.error || "Passkey unavailable");
  }
  return decodeRequestOptions(data.publicKey);
}

/** Passwordless sign-in when the server has registered passkeys (M03). */
export async function loginWithPasskey(): Promise<AuthLoginResponse> {
  if (
    typeof window === "undefined" ||
    !window.PublicKeyCredential ||
    !navigator.credentials?.get
  ) {
    throw new Error("Passkeys are not supported in this browser");
  }

  const publicKey = await getPasskeyLoginOptions();
  const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (!cred) {
    throw new Error("Passkey sign-in cancelled");
  }

  try {
    const data = await fetchJson<AuthLoginResponse>("/auth/passkey/login", {
      method: "POST",
      body: encodeAssertion(cred),
    });
    if (!data.ok) {
      throw new Error(data.error || "Passkey login failed");
    }
    await syncCsrfAfterLogin(data);
    return data;
  } catch (err) {
    if (err instanceof HermesApiError) {
      const payload = err.body as AuthLoginResponse | undefined;
      throw new Error(payload?.error || err.message);
    }
    throw err;
  }
}
