import { reactive } from 'vue'
import type { User } from './types'

const saved = localStorage.getItem('aibet-user')
export const auth = reactive<{ token:string; refresh:string; user:User|null }>({
  token: localStorage.getItem('aibet-token') || '',
  refresh: localStorage.getItem('aibet-refresh') || '',
  user: saved ? JSON.parse(saved) : null,
})
export function setAuth(token:string, refresh:string, user:User) {
  Object.assign(auth, { token, refresh, user })
  localStorage.setItem('aibet-token', token); localStorage.setItem('aibet-refresh', refresh); localStorage.setItem('aibet-user', JSON.stringify(user))
}
export function updateAuthUser(user:User) {
  if (!auth.user || auth.user.id !== user.id) return
  auth.user = user
  localStorage.setItem('aibet-user', JSON.stringify(user))
}
export function clearAuth() {
  Object.assign(auth, { token:'', refresh:'', user:null })
  localStorage.removeItem('aibet-token'); localStorage.removeItem('aibet-refresh'); localStorage.removeItem('aibet-user')
}
export function hasPermission(code:string) { return auth.user?.role === 'admin' || Boolean(auth.user?.permissions.includes(code)) }
