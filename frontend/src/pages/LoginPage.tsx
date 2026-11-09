import { FormEvent, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AlertCircle, ArrowRight, CheckCircle2, Cloud, Loader2, LockKeyhole, ShieldCheck, Sparkles } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'

export function LoginPage() {
  const { login, user, loading, error } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState('')

  useEffect(() => {
    if (user) navigate('/', { replace: true })
  }, [user, navigate])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setLocalError('')
    if (!email.trim() || !password) {
      setLocalError('Enter your email and password.')
      return
    }
    setSubmitting(true)
    try {
      await login(email.trim(), password)
      const target = (location.state as { from?: string } | null)?.from ?? '/'
      navigate(target, { replace: true })
    } catch {
      // error is surfaced from the auth context
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="grid min-h-screen bg-slate-50 lg:grid-cols-2">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-navy-950 p-12 lg:flex">
        <div className="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-aws-orange/15 blur-3xl" />
        <div className="absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-blue-600/20 blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-aws-orange text-sm font-extrabold text-navy-950">
              SBG
            </div>
            <div>
              <p className="text-sm font-bold text-white">AWS Student Builder Group</p>
              <p className="text-xs text-navy-200/70">SJB Institute of Technology, Bengaluru</p>
            </div>
          </div>

          <div className="mt-20 max-w-lg">
            <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-aws-orange">
              <Sparkles className="h-3 w-3" /> Recruitment cycle 2026–27
            </p>
            <h1 className="text-4xl font-extrabold leading-tight tracking-tight text-white">
              Evidence-backed recruitment, decided by people.
            </h1>
            <p className="mt-4 text-sm leading-relaxed text-navy-100/70">
              AI evaluates every application against a configurable rubric, surfaces evidence and flags uncertainty.
              Administrators review, rank and approve the interview shortlist.
            </p>
          </div>

          <div className="mt-10 space-y-3">
            {[
              'Deterministic Python scoring — the model never sets final marks',
              'Resume evidence, inconsistencies and missing information surfaced',
              'Role-wise rankings with human approval and a complete audit trail',
              'Private S3 storage, signed URLs and Cognito role-based access',
            ].map((item) => (
              <div key={item} className="flex items-start gap-2 text-sm text-navy-100/80">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-aws-orange" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="relative flex items-center gap-6 text-[11px] text-navy-200/50">
          <span className="inline-flex items-center gap-1.5"><Cloud className="h-3.5 w-3.5" /> AWS SAM · Lambda · DynamoDB</span>
          <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> Cognito protected</span>
        </div>
      </div>

      <div className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-aws-orange text-xs font-extrabold text-navy-950">SBG</div>
            <div>
              <p className="text-sm font-bold text-navy-900">AWS Student Builder Group</p>
              <p className="text-[11px] text-slate-500">SJBIT · Recruitment 2026–27</p>
            </div>
          </div>

          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle className="text-xl">Administrator sign in</CardTitle>
              <CardDescription>
                Access is limited to recruitment administrators, reviewers and viewers.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={onSubmit} className="space-y-4" noValidate>
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email address</Label>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="username"
                    placeholder="name@sjbit.edu.in"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    disabled={submitting}
                  />
                </div>

                {localError || error ? (
                  <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{localError || error}</span>
                  </div>
                ) : null}

                <Button type="submit" variant="accent" className="w-full" disabled={submitting || loading}>
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <LockKeyhole className="h-4 w-4" />}
                  {submitting ? 'Signing in…' : 'Sign in'}
                  {!submitting ? <ArrowRight className="h-4 w-4" /> : null}
                </Button>
              </form>
            </CardContent>
          </Card>

          <p className="mt-6 text-center text-[11px] leading-relaxed text-slate-400">
            By signing in you agree to handle applicant data confidentially. All administrative actions are audited.
          </p>
        </div>
      </div>
    </div>
  )
}
