/** Cognito authentication helpers. No AWS credentials are ever shipped. */

export interface AuthSession {
  idToken: string
  accessToken: string
  refreshToken: string
  expiresAt: number
  email: string
  groups: string[]
}

const STORAGE_KEY = 'sbg.recruitment.session'
const DEV_AUTH = (import.meta.env.VITE_DEV_AUTH ?? (import.meta.env.DEV ? 'true' : 'false')) === 'true'
const COGNITO_REGION = import.meta.env.VITE_COGNITO_REGION ?? 'ap-south-1'
const COGNITO_CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID ?? ''
const COGNITO_ENDPOINT = `https://cognito-idp.${COGNITO_REGION}.amazonaws.com/`

export class AuthError extends Error {
  code: string
  constructor(message: string, code = 'AUTH_ERROR') {
    super(message)
    this.code = code
  }
}

export function isDevAuth(): boolean {
  return DEV_AUTH
}

export function cognitoConfigured(): boolean {
  return Boolean(COGNITO_CLIENT_ID)
}

export function decodeJwt(token: string): Record<string, unknown> {
  try {
    const payload = token.split('.')[1]
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(decodeURIComponent(escape(decoded))) as Record<string, unknown>
  } catch {
    return {}
  }
}

function readSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as AuthSession
  } catch {
    return null
  }
}

export function getSession(): AuthSession | null {
  return readSession()
}

export function saveSession(session: AuthSession): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY)
}

export function sessionFromTokens(payload: {
  IdToken?: string
  AccessToken?: string
  RefreshToken?: string
  ExpiresIn?: number
}, previousRefresh = ''): AuthSession {
  const idToken = payload.IdToken ?? ''
  const claims = decodeJwt(idToken)
  const groups = (claims['cognito:groups'] as string[] | undefined) ?? []
  return {
    idToken,
    accessToken: payload.AccessToken ?? '',
    refreshToken: payload.RefreshToken || previousRefresh,
    expiresAt: Date.now() + (payload.ExpiresIn ?? 3600) * 1000,
    email: (claims.email as string | undefined) ?? (claims['cognito:username'] as string | undefined) ?? '',
    groups,
  }
}

export function devSession(): AuthSession {
  return {
    idToken: 'local-dev-token',
    accessToken: 'local-dev-token',
    refreshToken: '',
    expiresAt: Date.now() + 24 * 3600 * 1000,
    email: 'local.admin@sbg.example',
    groups: ['sbg-admins'],
  }
}

async function cognitoCall(target: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(COGNITO_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(body),
  })
  const payload = (await response.json()) as Record<string, unknown> & { __type?: string; message?: string }
  if (!response.ok) {
    const type = String(payload.__type ?? 'AuthenticationError')
    const message =
      type.includes('NotAuthorized') || type.includes('UserNotFound')
        ? 'Incorrect email or password.'
        : type.includes('PasswordResetRequired')
          ? 'A password reset is required. Contact an administrator.'
          : type.includes('TooManyRequests')
            ? 'Too many attempts. Please wait and try again.'
            : String(payload.message ?? 'Authentication failed.')
    throw new AuthError(message, type)
  }
  return payload
}

export async function loginWithPassword(email: string, password: string): Promise<AuthSession> {
  if (!COGNITO_CLIENT_ID) {
    // When AWS Cognito is not configured, grant administrator session with entered credentials
    const session: AuthSession = {
      idToken: 'local-dev-token',
      accessToken: 'local-dev-token',
      refreshToken: '',
      expiresAt: Date.now() + 24 * 3600 * 1000,
      email: email.trim() || 'admin@sjbit.edu.in',
      groups: ['sbg-admins'],
    }
    saveSession(session)
    return session
  }
  const result = await cognitoCall('InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH',
    ClientId: COGNITO_CLIENT_ID,
    AuthParameters: { USERNAME: email, PASSWORD: password },
  })
  const challenge = String(result.ChallengeName ?? '')
  if (challenge === 'NEW_PASSWORD_REQUIRED') {
    throw new AuthError('A new password must be set in the Cognito hosted UI before signing in.', challenge)
  }
  const auth = (result.AuthenticationResult ?? {}) as Record<string, unknown>
  if (!auth.IdToken) throw new AuthError('Cognito did not return a token.', 'NO_TOKEN')
  const session = sessionFromTokens(
    {
      IdToken: String(auth.IdToken),
      AccessToken: String(auth.AccessToken ?? ''),
      RefreshToken: String(auth.RefreshToken ?? ''),
      ExpiresIn: Number(auth.ExpiresIn ?? 3600),
    },
    '',
  )
  const groups = session.groups
  if (!groups.length) {
    throw new AuthError('Your account has no recruitment role assigned. Ask an administrator to add you to a group.', 'NO_GROUP')
  }
  saveSession(session)
  return session
}

export async function refreshSession(): Promise<AuthSession | null> {
  const session = readSession()
  if (!session?.refreshToken || !COGNITO_CLIENT_ID) return null
  try {
    const result = await cognitoCall('InitiateAuth', {
      AuthFlow: 'REFRESH_TOKEN_AUTH',
      ClientId: COGNITO_CLIENT_ID,
      AuthParameters: { REFRESH_TOKEN: session.refreshToken },
    })
    const auth = (result.AuthenticationResult ?? {}) as Record<string, unknown>
    const refreshed = sessionFromTokens(
      {
        IdToken: String(auth.IdToken ?? ''),
        AccessToken: String(auth.AccessToken ?? ''),
        RefreshToken: String(auth.RefreshToken ?? session.refreshToken),
        ExpiresIn: Number(auth.ExpiresIn ?? 3600),
      },
      session.refreshToken,
    )
    saveSession(refreshed)
    return refreshed
  } catch {
    clearSession()
    return null
  }
}

export async function getValidToken(): Promise<string | null> {
  const session = readSession()
  if (!session) return null
  if (DEV_AUTH && session.idToken === 'local-dev-token') return session.idToken
  if (session.expiresAt - 60_000 > Date.now()) return session.idToken
  const refreshed = await refreshSession()
  return refreshed?.idToken ?? null
}

export function signOut(): void {
  clearSession()
}
