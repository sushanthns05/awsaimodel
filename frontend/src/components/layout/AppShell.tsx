import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  BarChart3,
  CalendarCheck,
  FileSpreadsheet,
  LogOut,
  Menu,
  Settings2,
  Users,
  X,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react'
import { useAuth } from '../../hooks/useAuth'
import { cn, initials } from '../../lib/utils'
import { Button } from '../ui/button'

const NAVIGATION = [
  { to: '/', label: 'Overview', icon: BarChart3, permission: 'read', end: true },
  { to: '/applicants', label: 'Applicants', icon: Users, permission: 'read' },
  { to: '/shortlist', label: 'Shortlisting', icon: CalendarCheck, permission: 'read' },
  { to: '/reports', label: 'Reports', icon: FileSpreadsheet, permission: 'read' },
  { to: '/settings', label: 'Settings', icon: Settings2, permission: 'settings' },
]

const TITLES: Record<string, string> = {
  '/': 'Recruitment overview',
  '/applicants': 'Applicants',
  '/shortlist': 'Shortlisting',
  '/reports': 'Reports',
  '/settings': 'Settings',
}

export function AppShell() {
  const { user, logout, can } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const rootPath = `/${location.pathname.split('/')[1] ?? ''}`
  const title = TITLES[rootPath] ?? (location.pathname.startsWith('/applicants/') ? 'Applicant profile' : 'Recruitment')

  const nav = (
    <nav className="flex flex-1 flex-col gap-1 px-3 py-4">
      {NAVIGATION.filter((item) => can(item.permission)).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={() => setMobileOpen(false)}
          className={({ isActive }) => cn('app-sidebar-link', isActive && 'app-sidebar-link-active')}
        >
          <item.icon className="h-4 w-4" />
          <span className="flex-1">{item.label}</span>
          <ChevronRight className="h-3.5 w-3.5 opacity-40" />
        </NavLink>
      ))}
    </nav>
  )

  const sidebarInner = (
    <div className="flex h-full flex-col bg-gradient-to-b from-navy-950 via-navy-900 to-navy-950">
      <div className="flex items-center gap-3 border-b border-white/10 px-5 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-aws-orange text-sm font-extrabold text-navy-950 shadow-lg shadow-orange-900/30">
          SBG
        </div>
        <div>
          <p className="text-sm font-bold text-white">AWS Student Builder</p>
          <p className="text-[11px] text-navy-200/70">SJBIT · Recruitment 2026–27</p>
        </div>
      </div>
      {nav}
      <div className="border-t border-white/10 p-4">
        <div className="mb-3 flex items-center gap-2 rounded-md bg-white/5 px-3 py-2">
          <ShieldCheck className="h-3.5 w-3.5 text-aws-orange" />
          <span className="text-[10px] font-medium uppercase tracking-wide text-navy-100/70">
            {user?.groups?.[0]?.replace('sbg-', '') ?? 'viewer'} access
          </span>
        </div>
        <p className="px-1 text-[10px] leading-relaxed text-navy-200/40">
          AI assessments are recommendations. All shortlist decisions require human approval.
        </p>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-slate-50">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">{sidebarInner}</aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-navy-950/60" onClick={() => setMobileOpen(false)} />
          <aside className="relative h-full w-72">
            {sidebarInner}
            <button
              type="button"
              className="absolute -right-11 top-4 rounded-md bg-white p-2 shadow"
              onClick={() => setMobileOpen(false)}
              aria-label="Close menu"
            >
              <X className="h-4 w-4" />
            </button>
          </aside>
        </div>
      ) : null}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
          <div className="flex h-16 items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
            <div className="flex items-center gap-3">
              <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
                <Menu className="h-5 w-5" />
              </Button>
              <div>
                <h1 className="text-lg font-bold tracking-tight text-navy-900">{title}</h1>
                <p className="hidden text-[11px] text-slate-500 sm:block">
                  AWS Student Builder Group · SJB Institute of Technology · Bengaluru
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="hidden text-right sm:block">
                <p className="text-xs font-semibold text-navy-900">{user?.email || 'Administrator'}</p>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">
                  {user?.groups?.map((g) => g.replace('sbg-', '')).join(' · ') || 'local'}
                </p>
              </div>
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-navy-900 text-xs font-bold text-white">
                {initials(user?.email?.split('@')[0]?.replace('.', ' '))}
              </div>
              <Button variant="ghost" size="icon" onClick={logout} aria-label="Sign out" title="Sign out">
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1500px] px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
        <footer className="mx-auto w-full max-w-[1500px] px-4 pb-8 pt-2 text-[11px] text-slate-400 sm:px-6 lg:px-8">
          AWS Student Builder Group · SJB Institute of Technology · Recruitment cycle 2026–27 · AI-assisted, human-approved
        </footer>
      </div>
    </div>
  )
}
