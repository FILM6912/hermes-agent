/** Locators shared by legacy HTML shell and React Agent-UI shell. */
export const selectors = {
  loginForm: '[data-testid="login-form"], #login-form',
  loginUsername: '[data-testid="login-username"], #username',
  loginPassword: '[data-testid="login-password"], #pw',
  loginSubmit: '[data-testid="login-submit"], #login-form button[type="submit"]',
  /** Main app chrome after authentication (sidebar + composer or React shell root). */
  shell:
    '[data-testid="hermes-shell"], aside.sidebar, .composer-wrap, #composerWrap',
  reactRoot: '#root.hermes-app, [data-testid="hermes-shell"]',
} as const
