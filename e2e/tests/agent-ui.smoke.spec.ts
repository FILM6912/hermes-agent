import { expect, test } from '@playwright/test'

import {
  assertLoginAgentClasses,
  assertShellAgentClasses,
  isReactLogin,
  isReactShell,
} from '../fixtures/agentClasses.js'
import {
  assertServerReachable,
  credentialsFromEnv,
  ensureLoggedIn,
  fetchAuthStatus,
  submitLogin,
} from '../fixtures/auth.js'
import { selectors } from '../fixtures/selectors.js'

test.describe('Agent-UI login smoke', () => {
  test.beforeEach(async ({ request }) => {
    await assertServerReachable(request)
  })

  test('login page renders the sign-in form', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator(selectors.loginForm)).toBeVisible()
    await expect(page.locator(selectors.loginPassword)).toBeVisible()
  })

  test('login page exposes Agent-UI surface classes', async ({ page }) => {
    await page.goto('/login')
    test.skip(!(await isReactLogin(page)), 'legacy HTML login — Agent classes N/A')
    await assertLoginAgentClasses(page)
  })

  test('authenticated login redirects into the app', async ({
    page,
    request,
  }) => {
    const status = await fetchAuthStatus(request)
    test.skip(!status.auth_enabled, 'auth disabled — login flow not required')

    const creds = credentialsFromEnv()
    test.skip(
      !creds.password,
      'set HERMES_E2E_PASSWORD (and HERMES_E2E_USERNAME when multi-user) to run login',
    )

    await page.goto('/login')
    await submitLogin(page, {
      username: creds.username,
      password: creds.password!,
    })

    await expect(page).not.toHaveURL(/\/login(?:\?|$)/, { timeout: 15_000 })
    await expect(page.locator(selectors.shell).first()).toBeVisible({
      timeout: 15_000,
    })
  })
})

test.describe('Agent-UI shell smoke', () => {
  test.beforeEach(async ({ page, request }) => {
    await assertServerReachable(request)

    const status = await fetchAuthStatus(request)
    if (!status.auth_enabled) {
      await page.goto('/')
      return
    }

    const creds = credentialsFromEnv()
    test.skip(
      !creds.password,
      'set HERMES_E2E_PASSWORD (and HERMES_E2E_USERNAME when multi-user) for authenticated shell',
    )

    await ensureLoggedIn(page, request, {
      username: creds.username,
      password: creds.password!,
    })
  })

  test('main shell chrome is visible', async ({ page }) => {
    if (!page.url().includes('/login')) {
      await page.goto('/')
    }

    const shell = page.locator(selectors.shell).first()
    await expect(shell).toBeVisible()

    const reactRoot = page.locator(selectors.reactRoot)
    if (await reactRoot.count()) {
      await expect(reactRoot.first()).toBeVisible()
    }
  })

  test('shell exposes Agent-UI layout classes', async ({ page }) => {
    if (!page.url().includes('/login')) {
      await page.goto('/')
    }

    test.skip(!(await isReactShell(page)), 'legacy HTML shell — Agent classes N/A')
    await assertShellAgentClasses(page)
  })
})
