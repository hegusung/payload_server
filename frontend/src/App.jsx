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
  const [deployFile, setDeployFile] = useState(null)  // file row being deployed, or null
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
        {[['files', '📁 Files'], ['targets', '🚀 Targets'], ['presets', '🎨 Presets'], ['logs', '📋 Logs']].map(([t, label]) => (
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
        {tab === 'targets' && (
          <TargetsPanel server={server} token={token} showToast={showToast} />
        )}
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
                    <div className="flex gap-3 justify-end">
                      <button
                        onClick={() => setDeployFile(f)}
                        className="text-xs text-blue-400 hover:text-blue-300 opacity-0 group-hover:opacity-100 transition-opacity"
                      >Deploy</button>
                      <button
                        onClick={() => del(f.id)}
                        className="text-xs text-red-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                      >Delete</button>
                    </div>
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

      {deployFile && (
        <DeployModal
          server={server}
          token={token}
          file={deployFile}
          onClose={() => setDeployFile(null)}
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

function statusBadge(status) {
  const map = {
    deployed: 'bg-green-900/60 text-green-300 border-green-700/50',
    pending:  'bg-yellow-900/60 text-yellow-300 border-yellow-700/50',
    error:    'bg-red-900/60 text-red-300 border-red-700/50',
  }
  const cls = map[status] || 'bg-gray-800 text-gray-400 border-gray-700'
  return <span className={`text-xs px-2 py-0.5 rounded-full border ${cls}`}>{status}</span>
}

function StorageUrlExamples() {
  const examples = [
    { name: 'AWS S3', endpoint: 'Leave blank (AWS selects the endpoint)',
      detail: 'https://s3.<region>.amazonaws.com', region: 'e.g. eu-west-3',
      docs: 'https://docs.aws.amazon.com/AmazonS3/latest/userguide/VirtualHosting.html' },
    { name: 'Cloudflare R2', endpoint: 'https://<cloudflare-account-id>.r2.cloudflarestorage.com',
      detail: 'Copy the S3 API endpoint from R2 Overview. Use your Cloudflare account ID.', region: 'auto',
      docs: 'https://developers.cloudflare.com/r2/get-started/s3/' },
    { name: 'MinIO', endpoint: 'https://<your-minio-host>:<api-port>',
      detail: 'Use the S3 API address configured for your server, not the Console address.', region: 'Your server region',
      docs: 'https://github.com/minio/minio#quickstart' },
    { name: 'DigitalOcean Spaces', endpoint: 'https://<region>.digitaloceanspaces.com',
      detail: 'Example: https://nyc3.digitaloceanspaces.com', region: 'e.g. nyc3',
      docs: 'https://docs.digitalocean.com/products/spaces/reference/aws-sdks/' },
    { name: 'Backblaze B2', endpoint: 'https://s3.<region>.backblazeb2.com',
      detail: 'Copy the S3 endpoint from your bucket details.', region: 'e.g. us-west-004',
      docs: 'https://www.backblaze.com/docs/en/cloud-storage-call-the-s3-compatible-api' },
  ]

  return (
    <div className="mt-2 rounded-lg border border-gray-700 bg-gray-800/40 p-3 text-xs space-y-3">
      <p className="text-gray-300 font-medium">Endpoint URL examples</p>
      <p className="text-gray-400">Replace values in &lt;brackets&gt; with your settings. Enter the bucket separately; keep its name and object paths out of the endpoint URL.</p>
      {examples.map(example => (
        <div key={example.name} className="space-y-1">
          <a href={example.docs} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">{example.name}</a>
          <code className="block text-gray-200 break-all">{example.endpoint}</code>
          <p className="text-gray-400 break-words">{example.detail}</p>
          <p className="text-gray-500">Region: {example.region}</p>
        </div>
      ))}
    </div>
  )
}

function TargetsPanel({ server, token, showToast }) {
  const [providers, setProviders] = useState([])
  const [targets, setTargets]     = useState([])
  const [editing, setEditing]     = useState(null)  // null | target-with-config
  const [saving, setSaving]       = useState(false)
  const [health, setHealth]       = useState({})    // id -> {ok,message,checking}
  const [deletingBucket, setDeletingBucket] = useState(null)
  const [filesTarget, setFilesTarget] = useState(null)

  const load = async () => {
    try {
      const [prov, tgts] = await Promise.all([
        apiFetch(server, token, 'GET', '/providers'),
        apiFetch(server, token, 'GET', '/targets'),
      ])
      setProviders(prov)
      setTargets(tgts)
    } catch (e) { showToast(e.message, 'error') }
  }

  useEffect(() => { if (server && token) load() }, [])

  const startNew = () => {
    const p = providers[0]
    if (!p) { showToast('No providers available', 'error'); return }
    setEditing({ name: '', provider_key: p.key, config: {}, note: '' })
  }

  const providerDef = (key) => providers.find(p => p.key === key)

  const save = async () => {
    if (!editing.name.trim()) { showToast('Name required', 'error'); return }
    setSaving(true)
    try {
      if (editing.id) await apiFetch(server, token, 'PUT', `/targets/${editing.id}`, editing)
      else            await apiFetch(server, token, 'POST', '/targets', editing)
      showToast('Saved')
      setEditing(null)
      load()
    } catch (e) { showToast(e.message, 'error') }
    finally { setSaving(false) }
  }

  const del = async (id) => {
    if (!confirm('Delete this target? (deployment records for it are removed too)')) return
    try {
      await apiFetch(server, token, 'DELETE', `/targets/${id}`)
      setTargets(t => t.filter(x => x.id !== id))
      showToast('Deleted')
    } catch (e) { showToast(e.message, 'error') }
  }

  const checkHealth = async (id) => {
    setHealth(h => ({ ...h, [id]: { checking: true } }))
    try {
      const r = await apiFetch(server, token, 'POST', `/targets/${id}/health`)
      setHealth(h => ({ ...h, [id]: r }))
    } catch (e) {
      setHealth(h => ({ ...h, [id]: { ok: false, message: e.message } }))
    }
  }

  const deleteBucket = async (target) => {
    const isAzure = target.provider_key === 'azure'
    const resource = isAzure ? 'container' : 'bucket'
    const name = isAzure ? target.config.container : target.config.bucket
    if (!confirm(`Delete ${resource} "${name}" and this target? The ${resource} must be empty. Deployment records will also be removed.`)) return
    setDeletingBucket(target.id)
    try {
      await apiFetch(server, token, 'DELETE', `/targets/${target.id}?delete_${resource}=true`)
      setTargets(t => t.filter(x => x.id !== target.id))
      showToast(`${isAzure ? 'Container' : 'Bucket'} and target deleted`)
    } catch (e) { showToast(e.message, 'error') }
    finally { setDeletingBucket(null) }
  }

  const def = editing ? providerDef(editing.provider_key) : null

  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-200">Delivery Targets</h2>
          <p className="text-xs text-gray-500 mt-0.5">External destinations for staging payloads. Transforms &amp; padding are baked into the uploaded object; serve-time features (decoy 404, download counting, header spoof) do not apply to cloud-hosted files.</p>
        </div>
        <button onClick={startNew} className="text-xs bg-blue-700 hover:bg-blue-600 px-3 py-1.5 rounded font-medium">+ New target</button>
      </div>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
            <th className="pb-2 pr-4 font-medium">Name</th>
            <th className="pb-2 pr-4 font-medium">Provider</th>
            <th className="pb-2 pr-4 font-medium">Config</th>
            <th className="pb-2 pr-4 font-medium">Health</th>
            <th className="pb-2 pr-4 font-medium">Note</th>
            <th className="pb-2 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {targets.map(t => (
            <tr key={t.id} className="border-b border-gray-800/50 hover:bg-gray-900/40 group align-top">
              <td className="py-2.5 pr-4 text-gray-200 text-xs font-semibold">{t.name}</td>
              <td className="py-2.5 pr-4 text-orange-300 text-xs font-mono">{t.provider_key}</td>
              <td className="py-2.5 pr-4 text-gray-400 text-xs font-mono">
                {Object.entries(t.config).filter(([, v]) => v !== '' && v != null).map(([k, v]) => (
                  <div key={k}><span className="text-gray-600">{k}=</span>{String(v)}</div>
                ))}
              </td>
              <td className="py-2.5 pr-4 text-xs">
                {health[t.id]?.checking ? <span className="text-yellow-300">checking…</span>
                  : health[t.id] ? (health[t.id].ok
                      ? <span className="text-green-400" title={health[t.id].message}>● ok</span>
                      : <div className="text-red-400">
                          <span>● fail</span>
                          <p className="mt-1 max-w-xs whitespace-pre-wrap break-words">{health[t.id].message || 'Health check failed.'}</p>
                        </div>)
                  : <button onClick={() => checkHealth(t.id)} className="text-blue-400 hover:text-blue-300">check</button>}
              </td>
              <td className="py-2.5 pr-4 text-gray-500 text-xs italic">{t.note || '—'}</td>
              <td className="py-2.5 flex gap-3">
                <button onClick={() => setFilesTarget(t)} className="text-xs text-blue-400 hover:text-blue-300">Files</button>
                <button onClick={() => setEditing({ ...t, config: { ...t.config } })} className="text-xs text-blue-400 hover:text-blue-300 opacity-0 group-hover:opacity-100 transition-opacity">Edit</button>
                <button onClick={() => del(t.id)} disabled={deletingBucket !== null} className="text-xs text-red-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity">Delete target</button>
                {['s3', 'r2', 'azure'].includes(t.provider_key) && <button onClick={() => deleteBucket(t)} disabled={deletingBucket !== null}
                  className="text-xs text-red-500 hover:text-red-400 disabled:opacity-50">
                  {deletingBucket === t.id ? 'Deleting…' : t.provider_key === 'azure' ? 'Delete container' : 'Delete bucket'}
                </button>}
              </td>
            </tr>
          ))}
          {targets.length === 0 && (
            <tr><td colSpan={6} className="py-8 text-center text-gray-600 text-sm">No targets. Click "+ New target" to configure one.</td></tr>
          )}
        </tbody>
      </table>

      {filesTarget && <TargetFilesModal key={filesTarget.id} server={server} token={token}
        target={filesTarget} onClose={() => setFilesTarget(null)} showToast={showToast} />}

      {editing && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={e => e.target === e.currentTarget && setEditing(null)}>
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto space-y-4">
            <h3 className="text-base font-semibold">{editing.id ? 'Edit target' : 'New target'}</h3>

            <div>
              <label className="text-xs text-gray-400 block mb-1">Name</label>
              <input value={editing.name} onChange={e => setEditing(p => ({ ...p, name: e.target.value }))}
                placeholder="e.g. prod-r2"
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500" />
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">Provider</label>
              <select value={editing.provider_key} disabled={!!editing.id}
                onChange={e => setEditing(p => ({ ...p, provider_key: e.target.value, config: {} }))}
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500 disabled:opacity-50">
                {providers.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
              </select>
            </div>

            {def?.config_fields.map(f => (
              <div key={f.key}>
                <label className="text-xs text-gray-400 block mb-1">
                  {f.label}{f.required && <span className="text-red-400"> *</span>}
                  {f.help && <span className="text-gray-600 block font-normal mt-0.5">{f.help}</span>}
                </label>
                {f.type === 'bool' ? <input
                  type="checkbox"
                  checked={editing.config[f.key] === true}
                  onChange={e => setEditing(p => ({ ...p, config: { ...p.config, [f.key]: e.target.checked } }))}
                  className="accent-blue-500" /> : <input
                  type={f.type === 'password' ? 'password' : 'text'}
                  value={editing.config[f.key] ?? ''}
                  placeholder={f.placeholder || (f.secret && editing.id ? '•••••••• (unchanged)' : '')}
                  onChange={e => setEditing(p => ({ ...p, config: { ...p.config, [f.key]: e.target.value } }))}
                  className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-blue-500" />}
                {editing.provider_key === 's3' && f.key === 'endpoint_url' && <StorageUrlExamples />}
                {editing.provider_key === 'r2' && f.key === 'account_id' && (
                  <p className="mt-2 text-xs text-gray-400 break-all">S3 endpoint: https://{editing.config.account_id || '<cloudflare-account-id>'}.r2.cloudflarestorage.com · Region: auto</p>
                )}
                {editing.provider_key === 's3' && f.key === 'public_base_url' && (
                  <p className="mt-2 text-xs text-gray-400 break-words">
                    Enter the URL used to download objects, such as https://cdn.example.com.
                    For R2, use your enabled https://pub-&lt;id&gt;.r2.dev URL or a custom domain.
                    For Spaces, you can use https://&lt;bucket&gt;.&lt;region&gt;.cdn.digitaloceanspaces.com when its CDN is enabled.
                    The object key is appended to this URL. Public access must be configured separately.
                  </p>
                )}
              </div>
            ))}

            <div>
              <label className="text-xs text-gray-400 block mb-1">Note <span className="text-gray-600">(optional)</span></label>
              <input value={editing.note || ''} onChange={e => setEditing(p => ({ ...p, note: e.target.value }))}
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

function TargetFilesModal({ server, token, target, onClose, showToast }) {
  const [files, setFiles] = useState([])
  const [prefix, setPrefix] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [deleteErrors, setDeleteErrors] = useState([])

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const result = await apiFetch(server, token, 'GET', `/targets/${target.id}/files`)
      setFiles(result.files)
      setPrefix(result.prefix)
    } catch (e) { setError(e.message); setFiles([]) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const remove = async (refs, all = false) => {
    const destination = target.config.container || target.config.bucket
    if (!confirm(all
      ? `Delete all ${refs.length} displayed files from "${destination}"?`
      : `Delete "${refs[0]}" from "${destination}"?`)) return
    setBusy(true)
    setDeleteErrors([])
    try {
      const result = await apiFetch(server, token, 'POST', `/targets/${target.id}/files/delete`, { refs })
      setDeleteErrors(result.errors)
      if (result.deleted.length) showToast(`Deleted ${result.deleted.length} file${result.deleted.length === 1 ? '' : 's'}`)
      await load()
    } catch (e) { setDeleteErrors([{ ref: '', message: e.message }]) }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={e => !busy && e.target === e.currentTarget && onClose()}>
      <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold">Active files — {target.name}</h3>
            <p className="text-xs text-gray-400 mt-1">{target.config.container || target.config.bucket} · {files.length} files</p>
          </div>
          <button onClick={load} disabled={loading || busy} className="text-xs text-blue-400 disabled:opacity-50">Refresh</button>
        </div>
        <p className="text-xs text-gray-500">{prefix ? `Showing files with prefix "${prefix}".` : 'Showing all current files in this bucket or container.'} Historical versions and soft-deleted files are excluded.</p>
        {error && <p role="alert" className="text-sm text-red-400 whitespace-pre-wrap break-words">{error}</p>}
        {deleteErrors.map((item, index) => <p key={index} role="alert" className="text-xs text-red-400 break-words">{item.ref && `${item.ref}: `}{item.message}</p>)}
        {loading ? <p className="text-sm text-gray-400">Loading files…</p> : !error && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-gray-500 border-b border-gray-700"><tr>
                <th className="py-2 pr-3">File</th><th className="py-2 pr-3">Size</th>
                <th className="py-2 pr-3">Modified</th><th className="py-2"></th>
              </tr></thead>
              <tbody>{files.map(file => <tr key={file.ref} className="border-b border-gray-800">
                <td className="py-2 pr-3 max-w-sm break-all"><a href={file.url} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">{file.ref}</a></td>
                <td className="py-2 pr-3 whitespace-nowrap text-gray-400">{formatBytes(file.size)}</td>
                <td className="py-2 pr-3 text-gray-400">{file.modified_at ? new Date(file.modified_at).toLocaleString() : '—'}</td>
                <td className="py-2"><button onClick={() => remove([file.ref])} disabled={busy} className="text-red-400 disabled:opacity-50">Delete</button></td>
              </tr>)}</tbody>
            </table>
            {files.length === 0 && <p className="py-6 text-center text-gray-500">No active files.</p>}
          </div>
        )}
        <div className="flex justify-between gap-3 pt-2">
          <button onClick={() => remove(files.map(file => file.ref), true)} disabled={busy || loading || !!error || files.length === 0}
            className="text-sm text-red-400 disabled:opacity-50">{busy ? 'Deleting…' : 'Delete all files'}</button>
          <button onClick={onClose} disabled={busy} className="text-sm text-gray-400 disabled:opacity-50">Close</button>
        </div>
      </div>
    </div>
  )
}

function DeployModal({ server, token, file, onClose, showToast }) {
  const [targets, setTargets]         = useState([])
  const [deployments, setDeployments] = useState([])
  const [busy, setBusy]               = useState(false)

  const load = async () => {
    try {
      const [tgts, deps] = await Promise.all([
        apiFetch(server, token, 'GET', '/targets'),
        apiFetch(server, token, 'GET', `/deployments?file_id=${file.id}`),
      ])
      setTargets(tgts)
      setDeployments(deps)
    } catch (e) { showToast(e.message, 'error') }
  }

  useEffect(() => { load() }, [])

  // Poll while any deployment is pending.
  useEffect(() => {
    if (!deployments.some(d => d.status === 'pending')) return
    const t = setInterval(load, 1500)
    return () => clearInterval(t)
  }, [deployments])

  const deploy = async (target_id) => {
    setBusy(true)
    try {
      await apiFetch(server, token, 'POST', `/files/${file.id}/deploy`, { target_id })
      showToast('Deploy started')
      load()
    } catch (e) { showToast(e.message, 'error') }
    finally { setBusy(false) }
  }

  const undeploy = async (id) => {
    if (!confirm('Remove this deployment (deletes the remote object)?')) return
    try {
      await apiFetch(server, token, 'DELETE', `/deployments/${id}`)
      showToast('Removed')
      load()
    } catch (e) { showToast(e.message, 'error') }
  }

  const depFor = (tid) => deployments.find(d => d.target_id === tid)

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-40" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-xl max-h-[90vh] overflow-y-auto space-y-4">
        <div>
          <h2 className="text-base font-semibold text-white">Deploy payload</h2>
          <p className="text-xs text-gray-500 mt-0.5 font-mono text-green-400">{file.uri}</p>
        </div>

        {targets.length === 0 && (
          <div className="text-sm text-gray-500 bg-gray-800/50 rounded-lg p-4">
            No delivery targets configured. Add one in the <span className="text-blue-400">🚀 Targets</span> tab first.
          </div>
        )}

        <div className="space-y-2">
          {targets.map(t => {
            const d = depFor(t.id)
            return (
              <div key={t.id} className="flex items-center gap-3 bg-gray-800/50 rounded-lg px-3 py-2.5">
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-gray-200 font-medium">{t.name} <span className="text-xs text-orange-300 font-mono">({t.provider_key})</span></div>
                  {d && (
                    <div className="text-xs mt-1 flex items-center gap-2 flex-wrap">
                      {statusBadge(d.status)}
                      {d.public_url && <a href={d.public_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline font-mono truncate max-w-[22rem]">{d.public_url}</a>}
                      {d.error && <span className="text-red-400" title={d.error}>⚠ {d.error.slice(0, 60)}</span>}
                    </div>
                  )}
                </div>
                {d && <button onClick={() => undeploy(d.id)} className="text-xs text-red-500 hover:text-red-400">Remove</button>}
                <button onClick={() => deploy(t.id)} disabled={busy}
                  className="text-xs bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white px-3 py-1.5 rounded font-semibold">
                  {d ? 'Redeploy' : 'Deploy'}
                </button>
              </div>
            )
          })}
        </div>

        <div className="flex justify-end pt-2">
          <button onClick={onClose} className="text-sm text-gray-400 hover:text-gray-200 px-4 py-2">Close</button>
        </div>
      </div>
    </div>
  )
}
