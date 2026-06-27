export { AuthPage } from "./components/AuthPage";
export { PasskeyButton } from "./components/PasskeyButton";
export { AUTH_REFRESH_EVENT, notifyAuthRefresh } from "./authRefresh";
export { useAuthBoot, type UseAuthBootResult } from "./hooks/useAuthBoot";
export { useAuthRole, deriveAuthRole, type AuthRoleHelpers } from "./hooks/useAuthRole";
export type * from "./types";
export {
  getAuthStatus,
  isShellAuthenticated,
  login,
  logout,
  loginWithPasskey,
  getPasskeyLoginOptions,
  type AuthStatus,
  type AuthLoginResponse,
  type AuthLogoutResponse,
  type LoginParams,
} from "./services/authService";
