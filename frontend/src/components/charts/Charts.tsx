import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { humanise } from '../../lib/utils'

const STATUS_COLORS: Record<string, string> = {
  COMPLETED: '#059669',
  NEEDS_REVIEW: '#f59e0b',
  FAILED: '#dc2626',
  RECEIVED: '#94a3b8',
  QUEUED: '#3b82f6',
  EXTRACTING: '#6366f1',
  EXTRACTED: '#8b5cf6',
  EVALUATING: '#0ea5e9',
  SCORING: '#14b8a6',
}

const BAND_COLORS = ['#059669', '#0ea5e9', '#f59e0b', '#dc2626']

export function ScoreDistributionChart({ data }: { data: { label: string; count: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
        <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
        <Tooltip
          cursor={{ fill: '#f1f5f9' }}
          contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
          formatter={(value: number) => [`${value} applicants`, 'Count']}
        />
        <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={64}>
          {data.map((entry, index) => (
            <Cell key={entry.label} fill={BAND_COLORS[index % BAND_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function ProcessingDonut({ data }: { data: { status: string; count: number }[] }) {
  const filtered = data.filter((item) => item.count > 0)
  if (!filtered.length) {
    return <div className="flex h-[240px] items-center justify-center text-xs text-slate-400">No applications processed yet</div>
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie data={filtered} dataKey="count" nameKey="status" innerRadius={58} outerRadius={88} paddingAngle={2}>
          {filtered.map((entry) => (
            <Cell key={entry.status} fill={STATUS_COLORS[entry.status] ?? '#94a3b8'} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
          formatter={(value: number, name: string) => [`${value}`, humanise(name)]}
        />
        <Legend
          verticalAlign="bottom"
          iconType="circle"
          iconSize={8}
          formatter={(value: string) => <span style={{ fontSize: 11, color: '#64748b' }}>{humanise(value)}</span>}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}

export function RoleBarChart({ data }: { data: { name: string; applicants: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
        <YAxis
          type="category"
          dataKey="name"
          width={130}
          tick={{ fontSize: 11, fill: '#475569' }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          cursor={{ fill: '#f1f5f9' }}
          contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
          formatter={(value: number) => [`${value} applicants`, 'Applications']}
        />
        <Bar dataKey="applicants" fill="#0b1f3a" radius={[0, 5, 5, 0]} maxBarSize={22} />
      </BarChart>
    </ResponsiveContainer>
  )
}
