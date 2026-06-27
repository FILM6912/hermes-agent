import { expect, type Locator, type Page } from '@playwright/test'

/**
 * Agent-UI React markers for login and shell smoke tests.
 * Legacy HTML shell lacks these nodes — callers should skip when absent.
 */
export const agentClasses = {
  login: {
    form: '[data-testid="login-form"]',
    title: '#login-title',
    /** LoginPage mount animation (Agent-UI auth screen). */
    pageEnter: '.animate-auth-page-enter',
  },
  shell: {
    page: '[data-testid="hermes-shell-page"].hermes-app',
    rail: '.hermes-shell-page__rail',
    main: '.hermes-shell-page__main',
    layout:
      '[data-testid="hermes-shell"].shell-layout.shell-layout--enter.hermes-app',
    inner: '.shell-layout__inner',
  },
} as const

export async function isReactLogin(page: Page): Promise<boolean> {
  return (await page.locator(agentClasses.login.form).count()) > 0
}

export async function isReactShell(page: Page): Promise<boolean> {
  return (await page.locator(agentClasses.shell.page).count()) > 0
}

export async function expectLocatorHasClass(
  locator: Locator,
  className: string,
): Promise<void> {
  await expect(locator).toHaveClass(new RegExp(`\\b${escapeRegExp(className)}\\b`))
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Assert React login route mounts Agent-UI auth chrome. */
export async function assertLoginAgentClasses(page: Page): Promise<void> {
  await expect(page.locator(agentClasses.login.form)).toBeVisible()
  await expect(page.locator(agentClasses.login.title)).toBeVisible()
  await expect(page.locator(agentClasses.login.pageEnter)).toBeVisible()
}

/** Assert post-auth shell uses Agent-UI page rail + 3-panel layout classes. */
export async function assertShellAgentClasses(page: Page): Promise<void> {
  await expect(page.locator(agentClasses.shell.page)).toBeVisible()
  await expect(page.locator(agentClasses.shell.rail)).toBeVisible()
  await expect(page.locator(agentClasses.shell.main)).toBeVisible()

  const layout = page.locator(agentClasses.shell.layout).first()
  await expect(layout).toBeVisible()
  await expectLocatorHasClass(layout, 'hermes-shell')
  await expect(page.locator(agentClasses.shell.inner).first()).toBeVisible()
}
