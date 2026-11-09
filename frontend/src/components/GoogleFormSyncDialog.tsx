import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  FileSpreadsheet,
  Loader2,
  RefreshCw,
  Sparkles,
  Upload,
} from 'lucide-react'
import { api } from '../lib/api'
import { importGoogleFormResponses, parseCSV } from '../lib/googleSync'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Input } from './ui/input'
import { Label } from './ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs'
import { Textarea } from './ui/textarea'

const GOOGLE_FORM_URL =
  'https://docs.google.com/forms/d/e/1FAIpQLSch2mAwHMWOf6_AUcTYNJRHA2GwZ2t8Xrv41hbSEC8gVsTB7w/viewform'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function GoogleFormSyncDialog({ open, onOpenChange }: Props) {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'sheet' | 'csv' | 'webhook'>('sheet')
  const [sheetUrl, setSheetUrl] = useState('')
  const [csvText, setCsvText] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function handleSheetSync() {
    setError('')
    setMessage('')
    if (!sheetUrl.trim()) {
      setError('Please paste your Google Sheet link or spreadsheet ID.')
      return
    }
    setLoading(true)
    try {
      try {
        const res = await api.syncGoogleSheet(sheetUrl.trim())
        setMessage(`Successfully imported and evaluated ${res.imported} applicants from Google Sheet!`)
      } catch {
        let csvData = ''
        const match = sheetUrl.match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/)
        if (match) {
          const sheetId = match[1]
          const exportUrl = `https://docs.google.com/spreadsheets/d/${sheetId}/export?format=csv`
          const resp = await fetch(exportUrl)
          if (!resp.ok) throw new Error('Sheet is private. Set sharing to "Anyone with the link can view", or export as CSV.')
          csvData = await resp.text()
        }
        if (csvData) {
          const records = parseCSV(csvData)
          const result = importGoogleFormResponses(records)
          setMessage(`Successfully synced ${result.imported} candidate responses from Google Sheet!`)
        } else {
          throw new Error('Please ensure Google Sheet sharing is set to "Anyone with the link can view", or use CSV upload.')
        }
      }
      await queryClient.invalidateQueries()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleCsvImport() {
    setError('')
    setMessage('')
    if (!csvText.trim()) {
      setError('Paste CSV content or select a file first.')
      return
    }
    setLoading(true)
    try {
      const records = parseCSV(csvText)
      if (records.length === 0) {
        throw new Error('No valid response rows found in the CSV.')
      }
      const result = importGoogleFormResponses(records)
      setMessage(
        `Successfully imported ${result.imported} real responses from Google Form (${result.totalRows} total rows processed).`,
      )
      await queryClient.invalidateQueries()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (evt) => {
      const content = String(evt.target?.result || '')
      setCsvText(content)
      setMessage(`Loaded "${file.name}" (${content.split('\n').length - 1} response rows). Click "Import & Evaluate" below.`)
      setError('')
    }
    reader.onerror = () => setError('Failed to read file.')
    reader.readAsText(file)
  }

  return (
    <Dialog
      open={open}
      onClose={() => onOpenChange(false)}
      title="Link Google Form Responses"
      description="Connect real submissions from AWS Student Builder Group SJBIT Recruitment Form"
    >
      <div className="space-y-4">
        <div className="flex items-center justify-between rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-xs">
          <span className="text-slate-600 font-medium">Recruitment Google Form:</span>
          <a
            href={GOOGLE_FORM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-aws-orange hover:underline font-semibold flex items-center gap-1"
          >
            Open Live Form <ExternalLink className="h-3 w-3" />
          </a>
        </div>

        {message ? (
          <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
            <span>{message}</span>
          </div>
        ) : null}

        {error ? (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
            <span>{error}</span>
          </div>
        ) : null}

        <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="sheet">
              <FileSpreadsheet className="h-3.5 w-3.5 mr-1.5" /> Google Sheet
            </TabsTrigger>
            <TabsTrigger value="csv">
              <Upload className="h-3.5 w-3.5 mr-1.5" /> Upload CSV
            </TabsTrigger>
            <TabsTrigger value="webhook">
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Auto Webhook
            </TabsTrigger>
          </TabsList>

          <TabsContent value="sheet" className="space-y-3 pt-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold">Responses Google Sheet URL</Label>
              <Input
                placeholder="https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit"
                value={sheetUrl}
                onChange={(e) => setSheetUrl(e.target.value)}
                disabled={loading}
              />
              <p className="text-[11px] text-slate-500">
                In your Google Form, open the <strong>Responses</strong> tab and click the green{' '}
                <strong>"Link to Sheets"</strong> icon. Paste that spreadsheet link here.
              </p>
            </div>
            <div className="rounded-md border border-amber-200 bg-amber-50/60 p-2.5 text-[11px] text-amber-900">
              💡 Ensure the Google Sheet sharing setting is set to{' '}
              <strong>"Anyone with the link can view"</strong> so the recruitment system can pull submissions.
            </div>
            <Button variant="accent" size="sm" className="w-full" onClick={handleSheetSync} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <RefreshCw className="h-4 w-4 mr-1.5" />}
              {loading ? 'Syncing & Evaluating candidates…' : 'Sync Real Responses Now'}
            </Button>
          </TabsContent>

          <TabsContent value="csv" className="space-y-3 pt-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold">Upload Responses File (.csv)</Label>
              <div className="flex items-center gap-2">
                <input
                  type="file"
                  accept=".csv,text/csv"
                  id="csv-file-input"
                  className="hidden"
                  onChange={handleFileUpload}
                  disabled={loading}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full border-dashed"
                  onClick={() => document.getElementById('csv-file-input')?.click()}
                  disabled={loading}
                >
                  <Upload className="h-3.5 w-3.5 mr-1.5" /> Choose CSV file downloaded from Google Form
                </Button>
              </div>
              <p className="text-[11px] text-slate-500">
                In Google Forms → Responses tab → Click the 3 dots <strong>⋮</strong> → Choose{' '}
                <strong>"Download responses (.csv)"</strong>.
              </p>
            </div>

            {csvText ? (
              <div className="space-y-1">
                <Label className="text-[11px] text-slate-500">Preview / Paste CSV Text:</Label>
                <Textarea
                  rows={4}
                  value={csvText}
                  onChange={(e) => setCsvText(e.target.value)}
                  className="font-mono text-[11px]"
                  placeholder="Timestamp,Email Address,Full Name,USN..."
                />
              </div>
            ) : null}

            <Button variant="accent" size="sm" className="w-full" onClick={handleCsvImport} disabled={loading || !csvText.trim()}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <Sparkles className="h-4 w-4 mr-1.5" />}
              {loading ? 'Processing & Scoring with Gemini…' : 'Import & Evaluate Candidates'}
            </Button>
          </TabsContent>

          <TabsContent value="webhook" className="space-y-3 pt-2 text-xs text-slate-600">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
              <p className="font-semibold text-navy-900 flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" /> Real-time Google Apps Script Trigger
              </p>
              <p className="text-[11px] leading-relaxed">
                To have every submission appear automatically on this website the instant a student clicks "Submit":
              </p>
              <ol className="list-decimal list-inside space-y-1 text-[11px] text-slate-700 pl-1">
                <li>Open your Google Form or its linked Google Sheet.</li>
                <li>Go to <strong>Extensions → Apps Script</strong>.</li>
                <li>
                  Paste the code from <code className="font-mono bg-white px-1 border rounded">integrations/google-apps-script/Code.gs</code>.
                </li>
                <li>Set your Render endpoint URL and run the <code className="font-mono bg-white px-1 border rounded">setup()</code> function once.</li>
              </ol>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </Dialog>
  )
}

