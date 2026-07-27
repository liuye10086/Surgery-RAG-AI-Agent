import request from './request'

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface UserInfo {
  id: number
  username: string
  email: string
  real_name: string | null
  role: string
}

export interface RegisterData {
  username: string
  email: string
  real_name?: string
  password: string
}

export function register(data: RegisterData): Promise<TokenResponse> {
  return request.post('/v1/auth/register', data)
}

export function login(username: string, password: string): Promise<TokenResponse> {
  return request.post('/v1/auth/login/json', { username, password })
}

export function getMe(): Promise<UserInfo> {
  return request.get('/v1/auth/me')
}

export interface ExportDataResponse {
  exported_at: string
  user: UserInfo & { created_at: string }
  sessions: any[]
  audit_logs: any[]
}

export function exportData(): Promise<ExportDataResponse> {
  return request.get('/v1/user/export')
}

export function deleteAccount(password: string): Promise<void> {
  return request.delete('/v1/user/account', { data: { password } })
}
