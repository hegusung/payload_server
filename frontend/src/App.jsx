import { useState, useEffect, useRef } from 'react'

const TOKEN_KEY = 'ps_token'

function getToken() { return localStorage.getItem(TOKEN_KEY) || '' }
function getServer() { return window.location.origin }

async function apiFetch(server, token, method, path, body) {
  const url = `${server.replace(/\/$/, '')}/api${path}`
  const opts = {
    method,
    headers: { 'X-Token': token, 'Accept': 'application/json' },
  }
  if (body instanceof FormData) {
    opts.body = body
  } else if (body) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(url, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

function formatBytes(n) {
  if (n === 0) return '0 B'
  const k = 1024, sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(n) / Math.log(k))
  return (n / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i]
}

function formatDate(d) {
  if (!d) return '—'
  return new Date(d).toLocaleString()
}

function Toast({ msg, type, onDone }) {
  useEffect(() => { const t = setTimeout(onDone, 3000); return () => clearTimeout(t) }, [])
  const bg = type === 'error' ? 'bg-red-600' : 'bg-green-600'
  return (
    <div className={`fixed bottom-4 right-4 z-50 ${bg} text-white text-sm px-4 py-2.5 rounded-xl shadow-xl`}>
      {msg}
    </div>
  )
}

// auth status: 'unknown' | 'checking' | 'ok' | 'error'
export default function App() {
  const server = getServer()
  const [token, setToken]     = useState(getToken)
  const [files, setFiles]     = useState([])
  const [loading, setLoading] = useState(false)
  const [toast, setToast]     = useState(null)
  const [showUpload, setShowUpload] = useState(false)
  const [tab, setTab]         = useState('files')  // 'files' | 'presets' | 'logs'
  const [authStatus, setAuthStatus] = useState('unknown')  // 'unknown'|'checking'|'ok'|'error'
  const [authError, setAuthError]   = useState('')

  const showToast = (msg, type = 'success') => setToast({ msg, type })

  const checkAuth = async (srv, tok) => {
    if (!srv || !tok) { setAuthStatus('unknown'); return false }
    setAuthStatus('checking')
    try {
      await apiFetch(srv, tok, 'GET', '/files')
      setAuthStatus('ok')
      setAuthError('')
      return true
    } catch (e) {
      setAuthStatus('error')
      setAuthError(e.message)
      return false
    }
  }

  const save = async () => {
    localStorage.setItem(TOKEN_KEY, token)
    const ok = await checkAuth(server, token)
    if (ok) { showToast('Connected'); load() }
    else showToast(authError || 'Authentication failed', 'error')
  }

  const load = async () => {
    setLoading(true)
    try {
      const data = await apiFetch(server, token, 'GET', '/files')
      setFiles(data)
      setAuthStatus('ok')
    } catch (e) {
      showToast(e.message, 'error')
      setAuthStatus('error')
      setAuthError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (server && token) { checkAuth(server, token).then(ok => { if (ok) load() }) }
    else setAuthStatus('unknown')
  }, [])

  const del = async (id) => {
    if (!confirm('Delete this file?')) return
    try {
      await apiFetch(server, token, 'DELETE', `/files/${id}`)
      setFiles(f => f.filter(x => x.id !== id))
      showToast('Deleted')
    } catch (e) {
      showToast(e.message, 'error')
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3 flex items-center gap-4">
        <span className="text-lg font-semibold tracking-tight text-white">payload-server</span>
        <span className="text-xs text-gray-500 font-mono">file hosting</span>

        {/* Auth status badge */}
        {authStatus === 'unknown' && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-400 border border-gray-700">⚪ Not configured</span>
        )}
        {authStatus === 'checking' && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-900/60 text-yellow-300 border border-yellow-700/50">🟡 Connecting…</span>
        )}
        {authStatus === 'ok' && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/60 text-green-300 border border-green-700/50">🟢 Connected</span>
        )}
        {authStatus === 'error' && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-red-900/60 text-red-300 border border-red-700/50" title={authError}>🔴 {authError.includes('401') || authError.toLowerCase().includes('invalid') ? 'Invalid token' : authError.includes('fetch') || authError.includes('Failed') ? 'Server unreachable' : 'Auth error'}</span>
        )}

        <div className="ml-auto flex items-center gap-2">
          <input
            value={token}
            onChange={e => { setToken(e.target.value); setAuthStatus('unknown') }}
            placeholder="token"
            type="password"
            className={`w-32 bg-gray-900 rounded px-2 py-1 text-xs font-mono text-gray-200 focus:outline-none border ${
              authStatus === 'ok' ? 'border-green-600' : authStatus === 'error' ? 'border-red-600' : 'border-gray-700 focus:border-blue-500'
            }`}
          />
          <button onClick={save} className="text-xs bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded">Connect</button>
          <button onClick={load} disabled={authStatus !== 'ok'} className="text-xs bg-blue-700 hover:bg-blue-600 disabled:opacity-40 px-2 py-1 rounded">Refresh</button>
          {tab === 'files' && <button onClick={() => setShowUpload(true)} disabled={authStatus !== 'ok'} className="text-xs bg-red-700 hover:bg-red-600 disabled:opacity-40 px-2 py-1 rounded font-semibold">+ Upload</button>}
        </div>
      </header>

      {/* No-config banner */}
      {authStatus === 'unknown' && !server && (
        <div className="bg-yellow-900/30 border-b border-yellow-700/40 px-6 py-2 text-xs text-yellow-300">
          ⚠ Enter the server URL and token above, then click <strong>Connect</strong>.
        </div>
      )}
      {authStatus === 'error' && (
        <div className="bg-red-900/30 border-b border-red-700/40 px-6 py-2 text-xs text-red-300">
          🔴 <strong>Authentication failed</strong> — {authError}. Check your server URL and token.
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-800 px-6 flex gap-1">
        {[['files', '📁 Files'], ['presets', '🎨 Presets'], ['logs', '📋 Logs']].map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`text-xs px-3 py-2 font-medium transition ${
              tab === t ? 'text-white border-b-2 border-blue-500' : 'text-gray-500 hover:text-gray-300'
            }`}
          >{label}</button>
        ))}
      </div>

      {/* File list */}
      <main className="flex-1 p-6">
        {tab === 'presets' && (
          <PresetsPanel server={server} token={token} showToast={showToast} />
        )}
        {tab === 'logs' && (
          <LogsPanel server={server} token={token} showToast={showToast} />
        )}
        {tab === 'files' && loading && <div className="text-gray-500 text-sm">Loading…</div>}
        {tab === 'files' && !loading && files.length === 0 && (
          <div className="text-gray-600 text-sm text-center mt-20">No files hosted. Upload one to get started.</div>
        )}
        {tab === 'files' && files.length > 0 && (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
                <th className="pb-2 pr-4 font-medium">URI</th>
                <th className="pb-2 pr-4 font-medium">Content-Type</th>
                <th className="pb-2 pr-4 font-medium">Size</th>
                <th className="pb-2 pr-4 font-medium">Padding</th>
                <th className="pb-2 pr-4 font-medium">Transform</th>
                <th className="pb-2 pr-4 font-medium">Downloads</th>
                <th className="pb-2 pr-4 font-medium">Last download</th>
                <th className="pb-2 pr-4 font-medium">Note</th>
                <th className="pb-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {files.map(f => (
                <tr key={f.id} className="border-b border-gray-800/50 hover:bg-gray-900/40 group">
                  <td className="py-2.5 pr-4 font-mono text-green-400 text-xs">{f.uri}</td>
                  <td className="py-2.5 pr-4 text-orange-300 text-xs">{f.content_type}</td>
                  <td className="py-2.5 pr-4 text-gray-400 text-xs">{formatBytes(f.file_size)}</td>
                  <td className="py-2.5 pr-4 text-gray-400 text-xs font-mono">
                    {[f.prepend_bytes > 0 && `+${f.prepend_bytes}B pre`, f.append_bytes > 0 && `+${f.append_bytes}B post`].filter(Boolean).join(' ') || '—'}
                  </td>
                  <td className="py-2.5 pr-4 text-purple-300 text-xs font-mono">{f.transform || '—'}</td>
                  <td className="py-2.5 pr-4 text-gray-300 text-xs font-semibold">{f.downloads}</td>
                  <td className="py-2.5 pr-4 text-gray-500 text-xs">{formatDate(f.last_download)}</td>
                  <td className="py-2.5 pr-4 text-gray-500 text-xs italic">{f.note || '—'}</td>
                  <td className="py-2.5">
                    <button
                      onClick={() => del(f.id)}
                      className="text-xs text-red-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                    >Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>

      {showUpload && (
        <UploadModal
          server={server}
          token={token}
          onClose={() => setShowUpload(false)}
          onUploaded={(f) => { setFiles(prev => [f, ...prev.filter(x => x.uri !== f.uri)]); showToast('Uploaded') }}
          showToast={showToast}
        />
      )}

      {toast && <Toast msg={toast.msg} type={toast.type} onDone={() => setToast(null)} />}
    </div>
  )
}

function UploadModal({ server, token, onClose, onUploaded, showToast }) {
  const [uri, setUri]           = useState('/')
  const [ct, setCt]             = useState('application/octet-stream')
  const [prepend, setPrepend]   = useState(0)
  const [append, setAppend]     = useState(0)
  const [dlFilename, setDlFilename] = useState('')
  const [transform, setTransform]   = useState('')
  const [xorKey, setXorKey]     = useState(65)
  const [note, setNote]         = useState('')
  const [file, setFile]         = useState(null)
  const [saving, setSaving]     = useState(false)
  const fileRef = useRef()

  const TRANSFORMS = ['xor', 'base64', 'base64u', 'netbios', 'netbiosu']
  const hasXor = transform.split(',').map(s => s.trim()).includes('xor')

  const submit = async () => {
    if (!file) { showToast('Select a file', 'error'); return }
    if (!uri.trim()) { showToast('URI required', 'error'); return }
    setSaving(true)
    try {
      const fd = new FormData()
      fd.append('uri', uri.trim())
      fd.append('content_type', ct.trim())
      fd.append('prepend_bytes', prepend)
      fd.append('append_bytes', append)
      fd.append('dl_filename', dlFilename.trim())
      fd.append('transform', transform.trim())
      fd.append('xor_key', xorKey)
      fd.append('note', note.trim())
      fd.append('file', file)
      const result = await apiFetch(server, token, 'POST', '/files', fd)
      onUploaded(result)
      onClose()
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-40" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-[520px] max-h-[90vh] overflow-y-auto space-y-4" onClick={e => e.stopPropagation()}>
        <h2 className="text-base font-semibold text-white">Upload file</h2>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-400 block mb-1">URI <span className="text-gray-600">(e.g. /jquery.min.js)</span></label>
            <input value={uri} onChange={e => setUri(e.target.value)}
              className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Content-Type</label>
            <input value={ct} onChange={e => setCt(e.target.value)}
              className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-blue-500" />
          </div>
          <div className="flex gap-3">
            <div>
              <label className="text-xs text-gray-400 block mb-1">Prepend random bytes</label>
              <input type="number" min={0} value={prepend} onChange={e => setPrepend(Number(e.target.value))}
                className="w-36 bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">Append random bytes</label>
              <input type="number" min={0} value={append} onChange={e => setAppend(Number(e.target.value))}
                className="w-36 bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500" />
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Filename override <span className="text-gray-600">(Content-Disposition)</span></label>
            <input value={dlFilename} onChange={e => setDlFilename(e.target.value)} placeholder="jquery.min.js"
              className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">
              Transform pipeline <span className="text-gray-600">(comma-separated)</span>
            </label>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {TRANSFORMS.map(t => {
                const active = transform.split(',').map(s => s.trim()).filter(Boolean).includes(t)
                return (
                  <button key={t} type="button"
                    onClick={() => {
                      const parts = transform.split(',').map(s => s.trim()).filter(Boolean)
                      if (active) setTransform(parts.filter(p => p !== t).join(','))
                      else setTransform([...parts, t].join(','))
                    }}
                    className={`text-xs px-2 py-1 rounded font-mono border transition ${
                      active ? 'bg-purple-700 border-purple-500 text-white' : 'bg-gray-800 border-gray-600 text-gray-400 hover:border-gray-400'
                    }`}>{t}</button>
                )
              })}
            </div>
            <input value={transform} onChange={e => setTransform(e.target.value)} placeholder="e.g. xor,base64"
              className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-purple-500" />
            {hasXor && (
              <div className="mt-2">
                <label className="text-xs text-gray-400 block mb-1">XOR key (0–255)</label>
                <input type="number" min={0} max={255} value={xorKey} onChange={e => setXorKey(Number(e.target.value))}
                  className="w-24 bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-purple-500" />
                <span className="ml-2 text-xs text-gray-500 font-mono">0x{xorKey.toString(16).padStart(2,'0').toUpperCase()}</span>
              </div>
            )}
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Note <span className="text-gray-600">(optional)</span></label>
            <input value={note} onChange={e => setNote(e.target.value)}
              className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">File</label>
            <input type="file" ref={fileRef} onChange={e => setFile(e.target.files?.[0] || null)}
              className="text-sm text-gray-300" />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm text-gray-400 hover:text-gray-200 px-4 py-2">Cancel</button>
          <button onClick={submit} disabled={saving}
            className="text-sm bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold">
            {saving ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      </div>
    </div>
  )
}

const CHARSETS = ['binary', 'printable', 'alphanum']

function LogsPanel({ server, token, showToast }) {
  const [logs, setLogs]       = useState([])
  const [total, setTotal]     = useState(0)
  const [loading, setLoading] = useState(false)
  const [filterUri, setFilterUri] = useState('')
  const [page, setPage]       = useState(0)
  const PER_PAGE = 100

  const load = async (p = page, uri = filterUri) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: PER_PAGE, offset: p * PER_PAGE })
      if (uri) params.set('uri', uri)
      const data = await apiFetch(server, token, 'GET', `/logs?${params}`)
      setLogs(data.logs || [])
      setTotal(data.total || 0)
    } catch (e) { showToast(e.message, 'error') }
    finally { setLoading(false) }
  }

  useEffect(() => { if (server && token) load(0, '') }, [])

  const clearAll = async () => {
    if (!confirm('Clear ALL download logs?')) return
    try {
      const params = filterUri ? `?uri=${encodeURIComponent(filterUri)}` : ''
      await apiFetch(server, token, 'DELETE', `/logs${params}`)
      showToast('Logs cleared')
      load(0, filterUri)
    } catch (e) { showToast(e.message, 'error') }
  }

  const applyFilter = () => { setPage(0); load(0, filterUri) }

  const pages = Math.ceil(total / PER_PAGE)

  return (
    <div className="max-w-6xl">
      <div className="flex items-center gap-3 mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-200">Download Logs</h2>
          <p className="text-xs text-gray-500 mt-0.5">{total} total entries</p>
        </div>
        <div className="flex-1" />
        <input
          value={filterUri}
          onChange={e => setFilterUri(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applyFilter()}
          placeholder="Filter by URI…"
          className="w-48 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500"
        />
        <button onClick={applyFilter} className="text-xs bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded">Filter</button>
        <button onClick={() => { setFilterUri(''); setPage(0); load(0, '') }} className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1">Clear</button>
        <button onClick={() => load(page, filterUri)} className="text-xs bg-blue-700 hover:bg-blue-600 px-2 py-1 rounded">↻ Refresh</button>
        <button onClick={clearAll} className="text-xs bg-red-900/60 hover:bg-red-800/60 text-red-300 px-2 py-1 rounded border border-red-700/40">
          🗑 {filterUri ? 'Clear filtered' : 'Clear all'}
        </button>
      </div>

      {loading && <div className="text-gray-500 text-sm">Loading…</div>}

      {!loading && (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
              <th className="pb-2 pr-3 font-medium">Timestamp</th>
              <th className="pb-2 pr-3 font-medium">URI</th>
              <th className="pb-2 pr-3 font-medium">IP</th>
              <th className="pb-2 pr-3 font-medium">User-Agent</th>
              <th className="pb-2 pr-3 font-medium">Size</th>
            </tr>
          </thead>
          <tbody>
            {logs.map(l => (
              <tr key={l.id} className="border-b border-gray-800/40 hover:bg-gray-900/40">
                <td className="py-2 pr-3 text-gray-400 text-xs font-mono whitespace-nowrap">{l.ts ? new Date(l.ts).toLocaleString() : '—'}</td>
                <td className="py-2 pr-3 text-green-400 text-xs font-mono">
                  <button onClick={() => { setFilterUri(l.uri); setPage(0); load(0, l.uri) }} className="hover:underline">{l.uri}</button>
                </td>
                <td className="py-2 pr-3 text-yellow-300 text-xs font-mono">{l.remote_ip || '—'}</td>
                <td className="py-2 pr-3 text-gray-400 text-xs max-w-xs truncate" title={l.user_agent || ''}>{l.user_agent || '—'}</td>
                <td className="py-2 pr-3 text-gray-400 text-xs">{l.bytes_served ? formatBytes(l.bytes_served) : '—'}</td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr><td colSpan={5} className="py-8 text-center text-gray-600 text-sm">No download logs yet.</td></tr>
            )}
          </tbody>
        </table>
      )}

      {pages > 1 && (
        <div className="flex items-center gap-2 mt-4 text-xs text-gray-500">
          <button onClick={() => { const p = Math.max(0, page - 1); setPage(p); load(p, filterUri) }} disabled={page === 0}
            className="px-2 py-1 rounded bg-gray-800 disabled:opacity-30">← Prev</button>
          <span>Page {page + 1} / {pages}</span>
          <button onClick={() => { const p = Math.min(pages - 1, page + 1); setPage(p); load(p, filterUri) }} disabled={page >= pages - 1}
            className="px-2 py-1 rounded bg-gray-800 disabled:opacity-30">Next →</button>
        </div>
      )}
    </div>
  )
}

function PresetsPanel({ server, token, showToast }) {
  const [presets, setPresets] = useState([])
  const [editing, setEditing] = useState(null)  // null | preset object | {}
  const [saving, setSaving]   = useState(false)

  const load = async () => {
    try {
      const data = await apiFetch(server, token, 'GET', '/presets')
      setPresets(data)
    } catch (e) { showToast(e.message, 'error') }
  }

  useEffect(() => { if (server && token) load() }, [])

  const save = async () => {
    setSaving(true)
    try {
      if (editing.id) {
        await apiFetch(server, token, 'PUT', `/presets/${editing.id}`, editing)
      } else {
        await apiFetch(server, token, 'POST', '/presets', editing)
      }
      showToast('Saved')
      setEditing(null)
      load()
    } catch (e) { showToast(e.message, 'error') }
    finally { setSaving(false) }
  }

  const del = async (id) => {
    if (!confirm('Delete this preset?')) return
    try {
      await apiFetch(server, token, 'DELETE', `/presets/${id}`)
      setPresets(p => p.filter(x => x.id !== id))
      showToast('Deleted')
    } catch (e) { showToast(e.message, 'error') }
  }

  const blank = { content_type: '', magic_prepend: '', magic_append: '', random_charset: 'binary', note: '' }

  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-200">Content-Type Presets</h2>
          <p className="text-xs text-gray-500 mt-0.5">When a file is served, if its Content-Type matches a preset, the prepend/append padding will start with the magic bytes instead of pure random.</p>
        </div>
        <button onClick={() => setEditing(blank)}
          className="text-xs bg-blue-700 hover:bg-blue-600 px-3 py-1.5 rounded font-medium">+ New preset</button>
      </div>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
            <th className="pb-2 pr-4 font-medium">Content-Type</th>
            <th className="pb-2 pr-4 font-medium">Magic prepend (hex)</th>
            <th className="pb-2 pr-4 font-medium">Magic append (hex)</th>
            <th className="pb-2 pr-4 font-medium">Random charset</th>
            <th className="pb-2 pr-4 font-medium">Note</th>
            <th className="pb-2 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {presets.map(p => (
            <tr key={p.id} className="border-b border-gray-800/50 hover:bg-gray-900/40 group">
              <td className="py-2.5 pr-4 font-mono text-orange-300 text-xs">{p.content_type}</td>
              <td className="py-2.5 pr-4 font-mono text-blue-300 text-xs">{p.magic_prepend || '—'}</td>
              <td className="py-2.5 pr-4 font-mono text-blue-300 text-xs">{p.magic_append || '—'}</td>
              <td className="py-2.5 pr-4 text-gray-400 text-xs">{p.random_charset}</td>
              <td className="py-2.5 pr-4 text-gray-500 text-xs italic">{p.note || '—'}</td>
              <td className="py-2.5 flex gap-3">
                <button onClick={() => setEditing({...p})} className="text-xs text-blue-400 hover:text-blue-300 opacity-0 group-hover:opacity-100 transition-opacity">Edit</button>
                <button onClick={() => del(p.id)} className="text-xs text-red-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity">Delete</button>
              </td>
            </tr>
          ))}
          {presets.length === 0 && (
            <tr><td colSpan={6} className="py-8 text-center text-gray-600 text-sm">No presets. Click "+ New preset" to create one.</td></tr>
          )}
        </tbody>
      </table>

      {editing && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={e => e.target === e.currentTarget && setEditing(null)}>
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-lg space-y-4">
            <h3 className="text-base font-semibold">{editing.id ? 'Edit preset' : 'New preset'}</h3>

            <div>
              <label className="text-xs text-gray-400 block mb-1">Content-Type</label>
              <input value={editing.content_type} onChange={e => setEditing(p => ({...p, content_type: e.target.value}))}
                disabled={!!editing.id}
                placeholder="e.g. image/jpeg"
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-orange-500 disabled:opacity-50" />
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">Magic prepend <span className="text-gray-600">(hex, e.g. FFD8FFE0)</span></label>
              <input value={editing.magic_prepend} onChange={e => setEditing(p => ({...p, magic_prepend: e.target.value.toUpperCase().replace(/[^0-9A-F]/g,'')}))}
                placeholder="FFD8FFE0"
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-blue-500" />
              {editing.magic_prepend && <p className="text-xs text-gray-500 mt-1">{editing.magic_prepend.length / 2} bytes</p>}
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">Magic append <span className="text-gray-600">(hex, e.g. FFD9)</span></label>
              <input value={editing.magic_append} onChange={e => setEditing(p => ({...p, magic_append: e.target.value.toUpperCase().replace(/[^0-9A-F]/g,'')}))}
                placeholder="FFD9"
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-blue-500" />
              {editing.magic_append && <p className="text-xs text-gray-500 mt-1">{editing.magic_append.length / 2} bytes</p>}
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">Random charset <span className="text-gray-600">(used to fill the rest of the padding)</span></label>
              <div className="flex gap-2">
                {CHARSETS.map(c => (
                  <button key={c} onClick={() => setEditing(p => ({...p, random_charset: c}))}
                    className={`text-xs px-3 py-1.5 rounded border transition ${
                      editing.random_charset === c
                        ? 'bg-blue-700 border-blue-500 text-white'
                        : 'bg-gray-800 border-gray-600 text-gray-400 hover:border-gray-400'
                    }`}>{c}</button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">Note <span className="text-gray-600">(optional)</span></label>
              <input value={editing.note || ''} onChange={e => setEditing(p => ({...p, note: e.target.value}))}
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500" />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setEditing(null)} className="text-sm text-gray-400 hover:text-gray-200 px-4 py-2">Cancel</button>
              <button onClick={save} disabled={saving}
                className="text-sm bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold">
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
