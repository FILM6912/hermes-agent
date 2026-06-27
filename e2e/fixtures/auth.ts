import { expect, type APIRequestContext, type Page } from '@playwright/test'

import { selectors } from './selectors.js'

export type AuthStatus = {
  auth_enabled?: boolean
  multi_user?: boolean
  password_auth_enabled?: boolean
}

export async function fetchAuthStatus(
  request: APIRequestContext,
): Promise<AuthStatus> {
  const res = await request.get('/api/v1/auth/status')
  if (!res.ok()) {
    throw new Error(`auth/status failed: ${res.status()} ${res.statusText()}`)
  }
  return (await res.json()) as AuthStatus
}

export async function assertServerReachable(
  request: APIRequestContext,
): Promise<void> {
  const res = await request.get('/health')
  if (!res.ok()) {
    throw new Error(
      `Hermes server not reachable at base URL (GET /health → ${res.status()}). ` +
        'Start the app before running e2e — see e2e/README.md.',
    )
  }
}

export function credentialsFromEnv(): {
  username?: string
  password?: string
} {
  const password = process.env.HERMES_E2E_PASSWORD?.trim()
  const username = process.env.HERMES_E2E_USERNAME?.trim()
  return { username: username || undefined, password: password || undefined }
}

/** Open the app shell when auth is on (reuses an existing session when present). */
export async function ensureLoggedIn(
  page: Page,
  request: APIRequestContext,
  creds: { username?: string; password: string },
): Promise<void> {
  const status = await fetchAuthStatus(request)
  if (!status.auth_enabled) {
    await page.goto('/')
    return
  }

  await page.goto('/')
  if (!page.url().includes('/login')) {
    return
  }

  await page.goto('/login')
  await submitLogin(page, creds)
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/, { timeout: 15_000 })
}

/** Fill and submit the login form (legacy or React). */
export async function submitLogin(
  page: Page,
  creds: { username?: string; password: string },
): Promise<void> {
  const form = page.locator(selectors.loginForm)
  await form.waitFor({ state: 'visible' })

  const username = page.locator(selectors.loginUsername)
  if (creds.username && (await username.isVisible())) {
    await username.fill(creds.username)
  }

  await page.locator(selectors.loginPassword).fill(creds.password)
  await page.locator(selectors.loginSubmit).click()
}
