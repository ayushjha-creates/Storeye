// Authentication API client (cookie/session based).
//
// The backend issues an HttpOnly session cookie on login; the browser stores it
// and the shared client sends it with `credentials: 'include'`. Nothing secret
// is ever persisted in JS/localStorage.

import { api } from './client'

export interface AuthUser {
  id: string
  email: string | null
  name: string
  role: string
  store_id: string
  is_active: boolean
  last_login_at: string | null
  created_at: string
  store_name: string | null
  demo_store: boolean
}

export interface LoginResult {
  user: AuthUser
  expires_in_seconds: number
}

export interface MessageResult {
  message: string
}

export const authApi = {
  login: (email: string, password: string) =>
    api.post<LoginResult>('/api/auth/login', { email, password }),
  logout: () => api.post<MessageResult>('/api/auth/logout'),
  logoutAll: () => api.post<MessageResult>('/api/auth/logout-all'),
  me: () => api.get<AuthUser>('/api/auth/me'),
  changePassword: (currentPassword: string, newPassword: string, newPasswordConfirm: string) =>
    api.post<MessageResult>('/api/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
      new_password_confirm: newPasswordConfirm,
    }),
}
