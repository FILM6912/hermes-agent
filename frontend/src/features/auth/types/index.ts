export interface AuthPageProps {
  onLogin: (login?: import("../services/authService").AuthLoginResponse) => void | Promise<import("../services/authService").AuthStatus | null>;
}

export interface AuthFormData {
  username: string;
  password: string;
  confirmPassword: string;
}
