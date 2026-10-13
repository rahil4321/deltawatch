import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowLeft, ArrowRight, ArrowUpRight, BellRing, Check,
  CheckCheck, CheckCircle2, ChevronDown, ChevronRight, CircleHelp, Clock3,
  ExternalLink, Eye, FileClock, Filter, Globe2, History, LayoutDashboard,
  LoaderCircle, LockKeyhole, Plus, RefreshCw, ScanEye, Search, Settings2,
  ShieldCheck, SlidersHorizontal, Sparkles, Trash2, X,
} from 'lucide-react';
import { api, apiOrigin, artifactUrl } from './api.js';

const NAV = [
  { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
  { id: 'monitors', label: 'Monitored pages', icon: Globe2 },
  { id: 'history', label: 'Change history', icon: History },
];

function formatDate(value, empty = 'Not checked yet') {
  if (!value) return empty;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return empty;
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function timeAgo(value) {
  if (!value) return 'Never checked';
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function shortHost(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url || 'Unknown site'; }
}

function StatusPill({ status }) {
  const normalized = status || 'pending';
  const labels = { ok: 'Healthy', changed: 'Changed', filtered: 'Noise filtered', pending: 'Awaiting baseline', error: 'Check failed', blocked: 'Blocked' };
  const Icon = normalized === 'ok' ? CheckCircle2 : normalized === 'changed' ? Activity : normalized === 'filtered' ? Filter : normalized === 'error' || normalized === 'blocked' ? AlertTriangle : Clock3;
  return <span className={`status-pill status-${normalized}`}><Icon size={12} strokeWidth={2.2} />{labels[normalized] || normalized}</span>;
}

function Button({ children, variant = 'secondary', size = 'md', icon: Icon, className = '', ...props }) {
  return <button className={`button button-${variant} button-${size} ${className}`} {...props}>{Icon && <Icon size={size === 'sm' ? 14 : 16} />}{children}</button>;
}

function EmptyState({ icon: Icon = ScanEye, title, body, action, onAction }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={24} /></div><h3>{title}</h3><p>{body}</p>{action && <Button variant="primary" icon={Plus} onClick={onAction}>{action}</Button>}</div>;
}

function Modal({ title, eyebrow, children, onClose, wide = false }) {
  useEffect(() => {
    const handler = (event) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal-head"><div><div className="eyebrow">{eyebrow || 'DELTawATCH WORKSPACE'}</div><h2 id="modal-title">{title}</h2></div><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={18} /></button></div>
      {children}
    </section>
  </div>;
}

function MonitorForm({ initial, onSave, onClose, saving }) {
  const editing = Boolean(initial?.id);
  const [form, setForm] = useState(() => ({
    name: initial?.name || '', url: initial?.url || '', interval_minutes: initial?.interval_minutes || 60,
    selector: initial?.selector || '', ignore_selectors: (initial?.ignore_selectors || []).join('\n'),
    ignore_text: (initial?.ignore_text || []).join('\n'), min_change_percent: initial?.min_change_percent ?? 0.02,
    webhook_url: '', notification_email: initial?.notification_email || '', clear_webhook: false,
  }));
  const [advanced, setAdvanced] = useState(Boolean(initial?.selector || initial?.ignore_selectors?.length || initial?.ignore_text?.length || initial?.has_webhook || initial?.notification_email));
  const [error, setError] = useState('');
  const update = (key, value) => setForm((previous) => ({ ...previous, [key]: value }));
  const submit = async (event) => {
    event.preventDefault(); setError('');
    const payload = {
      name: form.name.trim(), url: form.url.trim(), interval_minutes: Number(form.interval_minutes),
      selector: form.selector.trim() || null,
      ignore_selectors: form.ignore_selectors.split('\n').map((item) => item.trim()).filter(Boolean),
      ignore_text: form.ignore_text.split('\n').map((item) => item.trim()).filter(Boolean),
      min_change_percent: Number(form.min_change_percent),
    };
    if (!editing || form.webhook_url.trim() || form.clear_webhook) payload.webhook_url = form.clear_webhook ? null : (form.webhook_url.trim() || null);
    if (!editing || form.notification_email.trim() !== (initial?.notification_email || '')) payload.notification_email = form.notification_email.trim() || null;
    try { await onSave(payload); } catch (err) { setError(err.message || 'Could not save monitor.'); }
  };
  return <form className="monitor-form" onSubmit={submit}>
    <label className="field-label">Monitor name <span>Required</span><input autoFocus required minLength={2} maxLength={80} value={form.name} onChange={(e) => update('name', e.target.value)} placeholder="e.g. Scholarship deadline" /></label>
    <label className="field-label">Public page URL <span>HTTPS recommended</span><input required type="url" value={form.url} onChange={(e) => update('url', e.target.value)} placeholder="https://example.com/announcements" /></label>
    <div className="form-two-col">
      <label className="field-label">Check interval<select value={form.interval_minutes} onChange={(e) => update('interval_minutes', e.target.value)}>{[[15,'Every 15 minutes'],[30,'Every 30 minutes'],[60,'Every hour'],[180,'Every 3 hours'],[360,'Every 6 hours'],[720,'Every 12 hours'],[1440,'Every 24 hours']].map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label className="field-label">Minimum change threshold <span>Percent of captured text</span><div className="input-suffix"><input type="number" min="0" max="50" step="0.01" value={form.min_change_percent} onChange={(e) => update('min_change_percent', e.target.value)} /><b>%</b></div></label>
    </div>
    <button className="advanced-toggle" type="button" onClick={() => setAdvanced(!advanced)}><SlidersHorizontal size={15} />{advanced ? 'Hide tuning options' : 'Tune regions, noise & alerts'}<ChevronDown size={15} className={advanced ? 'rotate-180' : ''} /></button>
    {advanced && <div className="advanced-fields">
      <label className="field-label">Watch only this CSS selector <span>Optional</span><input value={form.selector} onChange={(e) => update('selector', e.target.value)} placeholder="main .announcement, #pricing, article" /><small>Leave blank to watch the visible body text.</small></label>
      <label className="field-label">Ignore CSS selectors <span>One per line</span><textarea rows="2" value={form.ignore_selectors} onChange={(e) => update('ignore_selectors', e.target.value)} placeholder=".last-updated\n.ad-slot\n.live-clock" /><small>Matching elements are removed before text is compared.</small></label>
      <label className="field-label">Ignore exact text <span>One phrase per line</span><textarea rows="2" value={form.ignore_text} onChange={(e) => update('ignore_text', e.target.value)} placeholder="Updated just now\nVisitors online" /><small>Use this for known volatile phrases. Ignored text is removed before hashing.</small></label>
      <label className="field-label">Discord / Telegram webhook <span>{editing && initial?.has_webhook ? 'Configured · leave blank to keep current' : 'Optional'}</span><input type="url" value={form.webhook_url} onChange={(e) => update('webhook_url', e.target.value)} placeholder="Discord webhook or Telegram sendMessage URL" autoComplete="off" /><small>Only Discord or configured Telegram HTTPS API URLs are accepted. Secret URLs are never returned by the API.</small></label>
      {editing && initial?.has_webhook && <label className="check-line"><input type="checkbox" checked={form.clear_webhook} onChange={(e) => update('clear_webhook', e.target.checked)} /> Remove the existing webhook destination</label>}
      <label className="field-label">Email alert recipient <span>{editing && initial?.notification_email ? 'Leave unchanged to keep current' : 'Optional · SMTP must be configured by the backend'}</span><input type="email" value={form.notification_email} onChange={(e) => update('notification_email', e.target.value)} placeholder="you@example.com" autoComplete="email" /><small>Email delivery requires DELTAWATCH_SMTP_HOST and DELTAWATCH_SMTP_FROM in the backend environment.</small></label>
    </div>}
    {error && <div className="form-error"><AlertTriangle size={15} />{error}</div>}
    <div className="modal-actions"><Button type="button" onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" icon={saving ? LoaderCircle : Check} disabled={saving}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Create monitor'}</Button></div>
    <div className="form-footnote"><ShieldCheck size={14} />Private network addresses and embedded URL credentials are blocked.</div>
  </form>;
}

function ActivityRow({ event, onClick }) {
  return <button className="activity-row" onClick={onClick}>
    <span className="activity-glyph"><Activity size={16} /></span>
    <span className="activity-main"><strong>{event.summary || 'Website content changed'}</strong><small>{event.monitor_name || 'Monitored page'} <span className="dot-separator">·</span> {timeAgo(event.created_at)}</small></span>
    <span className="activity-pct">{Number(event.change_percent || 0).toFixed(2)}%</span><ChevronRight className="row-chevron" size={16} />
  </button>;
}

function MetricCard({ label, value, detail, icon: Icon, tint = 'mint', trend }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><span className={`metric-icon tint-${tint}`}><Icon size={17} /></span></div><div className="metric-value">{value}</div><div className="metric-bottom"><span>{detail}</span>{trend && <span className="metric-trend"><ArrowUpRight size={13} />{trend}</span>}</div></article>;
}

function MonitorTable({ monitors, onOpen, onCheck, onEdit, onDelete, checkingId, compact = false }) {
  if (!monitors.length) return <EmptyState icon={Globe2} title="Nothing watching yet" body="Add a public page and DeltaWatch will build a baseline on its first successful check." action="Add your first monitor" onAction={() => window.dispatchEvent(new CustomEvent('deltawatch:add-monitor'))} />;
  return <div className="table-wrap"><table className="monitor-table"><thead><tr><th>PAGE</th><th>STATUS</th><th>INTERVAL</th><th>LAST CHECKED</th><th className="action-col">ACTIONS</th></tr></thead><tbody>{monitors.map((monitor) => <tr key={monitor.id}>
    <td><button className="page-cell" onClick={() => onOpen(monitor)}><span className="site-favicon"><Globe2 size={16} /></span><span className="page-cell-copy"><strong>{monitor.name}</strong><small>{shortHost(monitor.url)}</small></span></button></td>
    <td><StatusPill status={monitor.last_status} />{monitor.last_error && <div className="inline-error" title={monitor.last_error}>{monitor.last_error}</div>}</td>
    <td className="mono-cell">{monitor.interval_minutes >= 60 ? `${monitor.interval_minutes / 60}h` : `${monitor.interval_minutes}m`}</td>
    <td><span className="last-check">{timeAgo(monitor.last_checked_at)}</span></td>
    <td><div className="table-actions"><button className="icon-button compact" title="Check now" aria-label={`Check ${monitor.name} now`} disabled={checkingId === monitor.id} onClick={() => onCheck(monitor)}>{checkingId === monitor.id ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>{!compact && <><button className="icon-button compact" title="Edit monitor" aria-label={`Edit ${monitor.name}`} onClick={() => onEdit(monitor)}><Settings2 size={15} /></button><button className="icon-button compact danger-hover" title="Delete monitor" aria-label={`Delete ${monitor.name}`} onClick={() => onDelete(monitor)}><Trash2 size={15} /></button></>}</div></td>
  </tr>)}</tbody></table></div>;
}

function DiffPreview({ event, onClick }) {
  return <button className="diff-preview" onClick={onClick}>
    <div className="diff-preview-top"><span className="diff-badge"><Activity size={12} />CONTENT CHANGE</span><span className="diff-date">{formatDate(event.created_at)}</span></div>
    <h3>{event.monitor_name || 'Monitored page'}</h3><p>{event.summary || 'Content changed between snapshots.'}</p>
    <div className="diff-preview-bottom"><span className="change-meter"><i style={{ width: `${Math.min(100, Math.max(4, Number(event.change_percent || 0) * 2))}%` }} /></span><span>{Number(event.change_percent || 0).toFixed(2)}% changed</span><ArrowRight size={15} /></div>
  </button>;
}

function PageTitle({ eyebrow, title, subtitle, children }) {
  return <div className="page-title-row"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{children && <div className="page-title-actions">{children}</div>}</div>;
}

function Dashboard({ summary, monitors, events, onAdd, onOpenMonitor, onOpenEvent, onViewAll, onCheck, checkingId }) {
  const weekBars = useMemo(() => {
    const now = new Date();
    const rows = Array.from({ length: 7 }, (_, index) => {
      const day = new Date(now); day.setDate(now.getDate() - (6 - index));
      const count = events.filter((item) => new Date(item.created_at).toDateString() === day.toDateString()).length;
      return { key: day.toLocaleDateString([], { weekday: 'short' }), count };
    });
    const peak = Math.max(1, ...rows.map((bar) => bar.count));
    return rows.map((bar) => ({ ...bar, height: Math.max(6, (bar.count / peak) * 100) }));
  }, [events]);
  const preview = events.slice(0, 4);
  return <>
    <PageTitle eyebrow="WORKSPACE / OVERVIEW" title="Change intelligence" subtitle="A clear signal from the noise across the pages you care about."><Button icon={Plus} variant="primary" onClick={onAdd}>Add monitor</Button></PageTitle>
    <div className="metric-grid">
      <MetricCard label="Pages monitored" value={summary?.monitors ?? monitors.length} detail={`${summary?.healthy_monitors ?? 0} with a successful check`} icon={Globe2} tint="mint" />
      <MetricCard label="Meaningful changes" value={summary?.changes_24h ?? 0} detail="Detected in the last 24 hours" icon={Activity} tint="violet" trend={undefined} />
      <MetricCard label="Noise filtered" value={summary?.filtered_checks ?? 0} detail="Checks below your threshold" icon={Filter} tint="blue" />
      <MetricCard label="Needs attention" value={summary?.attention_needed ?? 0} detail="Errors or blocked pages" icon={AlertTriangle} tint="amber" />
    </div>
    <div className="dashboard-grid">
      <section className="panel activity-panel"><div className="panel-head"><div><div className="eyebrow">SIGNAL FEED</div><h2>Recent changes</h2></div><button className="text-button" onClick={onViewAll}>View history <ArrowRight size={14} /></button></div>
        {preview.length ? <div className="activity-list">{preview.map((event) => <ActivityRow key={event.id} event={event} onClick={() => onOpenEvent(event)} />)}</div> : <div className="empty-inline"><div className="empty-icon small"><Sparkles size={19} /></div><div><strong>Your signal feed is quiet</strong><p>When a monitored page changes, the evidence will show up here.</p></div></div>}
        <div className="panel-foot"><span className="live-dot" />History updates as checks complete<span className="foot-spacer" /><span className="muted">{summary?.total_checks ?? 0} total checks run</span></div>
      </section>
      <section className="panel signal-panel"><div className="panel-head"><div><div className="eyebrow">LAST 7 DAYS</div><h2>Change activity</h2></div><span className="tiny-chip"><Activity size={12} />Local history</span></div>
        <div className="chart-area"><div className="chart-y-labels"><span>High</span><span>Medium</span><span>Low</span></div><div className="bar-chart">{weekBars.map((bar) => <div className="bar-column" key={bar.key}><div className="bar-track"><i style={{ height: `${bar.count ? Math.max(12, bar.height) : 5}%` }} /></div><span>{bar.key}</span></div>)}</div></div>
        <div className="chart-caption"><span>Change events only</span><span className="legend-dot" />{events.length} recent events loaded</div>
      </section>
    </div>
    <section className="panel monitors-preview"><div className="panel-head"><div><div className="eyebrow">YOUR WATCHLIST</div><h2>Monitored pages <span className="count-pill">{monitors.length}</span></h2></div><button className="text-button" onClick={onViewAll}>Manage pages <ArrowRight size={14} /></button></div>
      <MonitorTable monitors={monitors.slice(0, 5)} onOpen={onOpenMonitor} onCheck={onCheck} onEdit={onOpenMonitor} onDelete={onOpenMonitor} checkingId={checkingId} compact />
    </section>
    <div className="security-note"><ShieldCheck size={16} /><span><strong>Built to be careful by default.</strong> Private-network URLs are blocked, checks use bounded timeouts, and repeat changes are stored as snapshots.</span><button className="text-button" onClick={() => window.dispatchEvent(new CustomEvent('deltawatch:open-settings'))}>How it works <ArrowRight size={13} /></button></div>
  </>;
}

function MonitorDetail({ monitor, snapshots, events, loading, onBack, onCheck, onEdit, onDelete, onOpenEvent, checkingId }) {
  if (!monitor) return <EmptyState title="Monitor not found" body="This page may have been deleted." action="Back to monitors" onAction={onBack} />;
  const latest = snapshots[0];
  return <>
    <div className="back-row"><button className="text-button" onClick={onBack}><ArrowLeft size={15} />All monitored pages</button><span className="crumb-slash">/</span><span>{monitor.name}</span></div>
    <PageTitle eyebrow="MONITOR / DETAILS" title={monitor.name} subtitle={<span className="subtitle-url"><Globe2 size={14} /><a href={monitor.url} target="_blank" rel="noreferrer">{monitor.url}<ExternalLink size={12} /></a></span>}>
      <Button icon={Settings2} onClick={() => onEdit(monitor)}>Edit</Button><Button icon={checkingId === monitor.id ? LoaderCircle : RefreshCw} onClick={() => onCheck(monitor)} disabled={checkingId === monitor.id}>{checkingId === monitor.id ? 'Checking…' : 'Check now'}</Button><Button icon={Trash2} variant="danger-quiet" onClick={() => onDelete(monitor)}>Delete</Button>
    </PageTitle>
    <div className="detail-meta-grid"><div className="detail-meta"><span>Current status</span><StatusPill status={monitor.last_status} /></div><div className="detail-meta"><span>Check interval</span><strong><Clock3 size={14} />{monitor.interval_minutes >= 60 ? `${monitor.interval_minutes / 60} hours` : `${monitor.interval_minutes} minutes`}</strong></div><div className="detail-meta"><span>Last checked</span><strong>{formatDate(monitor.last_checked_at)}</strong></div><div className="detail-meta"><span>Next check</span><strong>{formatDate(monitor.next_check_at, 'Scheduled')}</strong></div></div>
    {monitor.last_error && <div className="error-banner"><AlertTriangle size={17} /><div><strong>Latest check could not complete</strong><p>{monitor.last_error}</p></div></div>}
    <div className="detail-content-grid">
      <section className="panel baseline-panel"><div className="panel-head"><div><div className="eyebrow">LATEST SNAPSHOT</div><h2>Captured page</h2></div><span className="tiny-chip"><CheckCheck size={12} />{latest ? 'Baseline stored' : 'Waiting for first check'}</span></div>
        {latest?.screenshot_url ? <a className="screenshot-link" href={artifactUrl(latest.screenshot_url)} target="_blank" rel="noreferrer"><img src={artifactUrl(latest.screenshot_url)} alt="Latest captured page screenshot" /><span><Eye size={14} />Open full screenshot <ExternalLink size={12} /></span></a> : <div className="screenshot-empty"><ScanEye size={28} /><strong>{loading ? 'Loading page history…' : 'No snapshot yet'}</strong><p>Run a check to capture this page and establish its baseline.</p></div>}
        {latest && <div className="snapshot-meta"><span><FileClock size={14} />{formatDate(latest.created_at)}</span><span>{Number(latest.text_length || 0).toLocaleString()} characters captured</span><span title={latest.content_hash}>SHA-256 · {latest.content_hash?.slice(0, 10)}…</span></div>}
      </section>
      <section className="panel detail-events-panel"><div className="panel-head"><div><div className="eyebrow">VERSION HISTORY</div><h2>Meaningful changes</h2></div><span className="count-pill">{events.length}</span></div>
        {events.length ? <div className="detail-event-list">{events.map((event) => <button className="detail-event" key={event.id} onClick={() => onOpenEvent(event)}><span className="timeline-node"><Activity size={14} /></span><span className="detail-event-body"><strong>{event.summary}</strong><small>{formatDate(event.created_at)}</small></span><ChevronRight size={15} /></button>)}</div> : <div className="empty-small"><Sparkles size={18} /><strong>No content changes yet</strong><p>First captures create a baseline. Real changes appear here after a later check.</p></div>}
      </section>
    </div>
    <section className="panel snapshots-panel"><div className="panel-head"><div><div className="eyebrow">CAPTURE LOG</div><h2>Recent snapshots</h2></div><span className="muted">{snapshots.length} loaded</span></div>
      {snapshots.length ? <div className="snapshot-list">{snapshots.map((snapshot, index) => <div className="snapshot-row" key={snapshot.id}><span className={`snapshot-dot ${index === 0 ? 'current' : ''}`} /><div className="snapshot-row-main"><strong>{snapshot.title || monitor.name}</strong><small>{formatDate(snapshot.created_at)} <span className="dot-separator">·</span> {snapshot.text_length?.toLocaleString()} characters</small></div>{index === 0 && <span className="current-label">LATEST</span>}{snapshot.screenshot_url && <a className="icon-button compact" href={artifactUrl(snapshot.screenshot_url)} target="_blank" rel="noreferrer" aria-label="Open snapshot screenshot"><ExternalLink size={14} /></a>}</div>)}</div> : <div className="empty-small">No captures stored yet.</div>}
    </section>
  </>;
}

function HistoryPage({ events, monitors, onOpenEvent, search, setSearch }) {
  const filteredEvents = events.filter((event) => `${event.monitor_name || ''} ${event.summary || ''} ${event.monitor_url || ''}`.toLowerCase().includes(search.toLowerCase()));
  return <><PageTitle eyebrow="WORKSPACE / HISTORY" title="Change history" subtitle="An evidence trail for every meaningful content change."><div className="search-box"><Search size={15} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search changes…" aria-label="Search change history" /></div></PageTitle>
    {filteredEvents.length ? <div className="history-grid">{filteredEvents.map((event) => <DiffPreview key={event.id} event={event} onClick={() => onOpenEvent(event)} />)}</div> : <EmptyState icon={History} title={search ? 'No matching changes' : 'Your change history is empty'} body={search ? 'Try a different page name or change summary.' : 'When a page changes after its baseline is captured, a verified change record will appear here.'} />}
  </>;
}

function SettingsPage({ health, summary, onRefresh }) {
  return <><PageTitle eyebrow="WORKSPACE / SYSTEM" title="System & settings" subtitle="Configuration and operational details for this local DeltaWatch instance."><Button icon={RefreshCw} onClick={onRefresh}>Refresh status</Button></PageTitle>
    <div className="settings-grid"><section className="panel settings-card"><div className="settings-card-icon"><Activity size={19} /></div><h2>API connection</h2><p>Frontend requests are sent to the configured backend origin.</p><div className="settings-kv"><span>API origin</span><code>{apiOrigin()}</code></div><div className="settings-kv"><span>Connection</span><StatusPill status={health ? 'ok' : 'error'} /></div><div className="settings-kv"><span>Health endpoint</span><a href={`${apiOrigin()}/docs`} target="_blank" rel="noreferrer">Open API docs <ExternalLink size={12} /></a></div></section>
      <section className="panel settings-card"><div className="settings-card-icon blue"><LockKeyhole size={19} /></div><h2>Safety & privacy</h2><p>Controls designed for monitoring public pages responsibly.</p><div className="setting-bullet"><Check size={14} /><span>Local, private, loopback and reserved IPs are rejected.</span></div><div className="setting-bullet"><Check size={14} /><span>Every browser request and redirect is revalidated.</span></div><div className="setting-bullet"><Check size={14} /><span>Webhook secrets are not returned in API responses.</span></div><div className="setting-bullet"><Check size={14} /><span>Checks use bounded timeouts and limited worker concurrency.</span></div></section>
      <section className="panel settings-card"><div className="settings-card-icon violet"><FileClock size={19} /></div><h2>Current instance</h2><p>Data is stored in the backend's SQLite database and local artifact directory.</p><div className="settings-kv"><span>Monitored pages</span><strong>{summary?.monitors ?? '—'}</strong></div><div className="settings-kv"><span>Total checks</span><strong>{summary?.total_checks ?? '—'}</strong></div><div className="settings-kv"><span>Scheduler</span><span className="plain-status"><span className="live-dot" />Configured at backend startup</span></div></section>
      <section className="panel settings-card"><div className="settings-card-icon amber"><BellRing size={19} /></div><h2>Notifications</h2><p>Configure a Discord webhook or a Telegram bot sendMessage URL per monitor.</p><div className="setting-bullet"><Check size={14} /><span>Notifications fire only for a change that passes the configured threshold.</span></div><div className="setting-bullet"><Check size={14} /><span>Transient webhook failures are recorded without failing the browser capture.</span></div><div className="settings-callout">Do not share webhook URLs. Anyone with access to a webhook URL may be able to post to that channel.</div></section></div>
  </>;
}

function EventModal({ event, onClose }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    setLoading(true); setError('');
    api(`/api/events/${event.id}`).then((data) => { if (alive) setDetail(data); }).catch((err) => { if (alive) setError(err.message); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [event.id]);
  return <Modal title="Change evidence" eyebrow="EVENT / FORENSIC VIEW" onClose={onClose} wide>
    <div className="event-modal-content">
      <div className="event-modal-intro"><span className="diff-badge"><Activity size={12} />VERIFIED TEXT DIFFERENCE</span><h3>{event.monitor_name || 'Website content changed'}</h3><p>{detail?.summary || event.summary}</p><div className="event-meta-line"><span><Clock3 size={13} />{formatDate(event.created_at)}</span><span><Globe2 size={13} />{event.monitor_url || detail?.current_snapshot?.final_url || 'Monitored page'}</span><span>{Number(event.change_percent || 0).toFixed(3)}% text changed</span></div></div>
      {loading ? <div className="loading-box"><LoaderCircle className="spin" size={20} />Loading snapshot evidence…</div> : error ? <div className="form-error"><AlertTriangle size={15} />{error}</div> : <>
        {detail?.image_diff_url && <div className="image-diff-block"><div className="section-mini-title">SCREENSHOT DIFFERENCE</div><a href={artifactUrl(detail.image_diff_url)} target="_blank" rel="noreferrer"><img src={artifactUrl(detail.image_diff_url)} alt="Amplified screenshot pixel difference" /></a><small>This amplified pixel difference helps locate visual movement. It is complementary evidence; the text diff below determines whether the content changed.</small></div>}
        <div className="diff-columns"><section className="diff-column removed"><div className="diff-column-head"><span className="diff-symbol">−</span><strong>Removed</strong><span>{(detail?.removed_text || '').length} chars</span></div><pre>{detail?.removed_text || 'No removed text was captured.'}</pre></section><section className="diff-column added"><div className="diff-column-head"><span className="diff-symbol">+</span><strong>Added</strong><span>{(detail?.added_text || '').length} chars</span></div><pre>{detail?.added_text || 'No added text was captured.'}</pre></section></div>
        <div className="event-snapshots"><div><span>Before</span><strong>{detail?.previous_snapshot?.title || 'Previous snapshot'}</strong><small>{formatDate(detail?.previous_snapshot?.created_at)}</small>{detail?.previous_snapshot?.screenshot_url && <a href={artifactUrl(detail.previous_snapshot.screenshot_url)} target="_blank" rel="noreferrer">Open screenshot <ExternalLink size={12} /></a>}</div><div><span>After</span><strong>{detail?.current_snapshot?.title || 'Current snapshot'}</strong><small>{formatDate(detail?.current_snapshot?.created_at)}</small>{detail?.current_snapshot?.screenshot_url && <a href={artifactUrl(detail.current_snapshot.screenshot_url)} target="_blank" rel="noreferrer">Open screenshot <ExternalLink size={12} /></a>}</div></div>
      </>}
      <div className="modal-actions"><Button onClick={onClose}>Close evidence</Button>{(event.monitor_url || detail?.current_snapshot?.final_url) && <a className="button button-secondary button-md link-button" href={event.monitor_url || detail?.current_snapshot?.final_url} target="_blank" rel="noreferrer">Open website <ExternalLink size={14} /></a>}</div>
    </div>
  </Modal>;
}

function ConfirmDelete({ monitor, onCancel, onConfirm, busy }) {
  return <Modal title="Delete monitor?" eyebrow="CONFIRM ACTION" onClose={onCancel}><div className="confirm-delete"><div className="confirm-delete-icon"><Trash2 size={22} /></div><p><strong>{monitor.name}</strong> and its saved snapshots and change history will be permanently deleted from this instance.</p><p className="muted">This action cannot be undone.</p></div><div className="modal-actions"><Button onClick={onCancel}>Keep monitor</Button><Button variant="danger" icon={Trash2} onClick={onConfirm} disabled={busy}>{busy ? 'Deleting…' : 'Delete permanently'}</Button></div></Modal>;
}

export default function App() {
  const [page, setPage] = useState('dashboard');
  const [summary, setSummary] = useState(null);
  const [monitors, setMonitors] = useState([]);
  const [events, setEvents] = useState([]);
  const [health, setHealth] = useState(false);
  const [globalError, setGlobalError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [modal, setModal] = useState(null);
  const [selectedMonitorId, setSelectedMonitorId] = useState(null);
  const [snapshots, setSnapshots] = useState([]);
  const [monitorEvents, setMonitorEvents] = useState([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [eventToView, setEventToView] = useState(null);
  const [search, setSearch] = useState('');
  const [monitorSearch, setMonitorSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [checkingId, setCheckingId] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [toast, setToast] = useState(null);

  const selectedMonitor = monitors.find((monitor) => monitor.id === selectedMonitorId) || null;
  const notify = useCallback((message, type = 'success') => {
    const id = Date.now() + Math.random();
    setToast({ message, type, id });
    window.setTimeout(() => setToast((current) => current?.id === id ? null : current), 3600);
  }, []);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setRefreshing(true);
    try {
      const [healthResult, dashboardResult, monitorsResult, eventsResult] = await Promise.all([
        api('/api/health'), api('/api/dashboard'), api('/api/monitors'), api('/api/events?limit=60'),
      ]);
      setHealth(healthResult.status === 'ok'); setSummary(dashboardResult); setMonitors(monitorsResult); setEvents(eventsResult); setGlobalError('');
    } catch (error) {
      setHealth(false); setGlobalError(error.message || 'Could not load DeltaWatch data.');
    } finally { if (!quiet) setRefreshing(false); }
  }, []);

  useEffect(() => { refresh(); const timer = window.setInterval(() => refresh(true), 7000); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => {
    const requestedId = Number(new URLSearchParams(window.location.search).get('event'));
    if (!requestedId || !events.length || eventToView?.id === requestedId) return;
    const matched = events.find((event) => event.id === requestedId);
    if (matched) setEventToView(matched);
  }, [events, eventToView]);
  useEffect(() => {
    const addHandler = () => setModal({ type: 'monitor' });
    const settingsHandler = () => setPage('settings');
    window.addEventListener('deltawatch:add-monitor', addHandler);
    window.addEventListener('deltawatch:open-settings', settingsHandler);
    return () => { window.removeEventListener('deltawatch:add-monitor', addHandler); window.removeEventListener('deltawatch:open-settings', settingsHandler); };
  }, []);

  const openMonitor = async (monitor) => {
    setSelectedMonitorId(monitor.id); setPage('monitor-detail'); setDetailLoading(true); setSnapshots([]); setMonitorEvents([]);
    try {
      const [snapshotResult, eventResult] = await Promise.all([api(`/api/monitors/${monitor.id}/snapshots?limit=30`), api(`/api/monitors/${monitor.id}/events?limit=30`)]);
      setSnapshots(snapshotResult); setMonitorEvents(eventResult);
    } catch (error) { notify(error.message, 'error'); }
    finally { setDetailLoading(false); }
  };

  useEffect(() => {
    if (page !== 'monitor-detail' || !selectedMonitorId) return undefined;
    let alive = true;
    const load = async () => {
      try {
        const [snapshotResult, eventResult] = await Promise.all([api(`/api/monitors/${selectedMonitorId}/snapshots?limit=30`), api(`/api/monitors/${selectedMonitorId}/events?limit=30`)]);
        if (alive) { setSnapshots(snapshotResult); setMonitorEvents(eventResult); }
      } catch { /* The global refresh and explicit actions still surface actionable errors. */ }
    };
    const timer = window.setInterval(load, 6500);
    return () => { alive = false; window.clearInterval(timer); };
  }, [page, selectedMonitorId]);

  const openEvent = (event) => {
    const url = new URL(window.location.href);
    if (url.searchParams.has('event')) {
      url.searchParams.delete('event');
      window.history.replaceState({}, '', url);
    }
    setEventToView(event);
  };
  const closeEvent = () => {
    setEventToView(null);
    const url = new URL(window.location.href);
    if (url.searchParams.has('event')) {
      url.searchParams.delete('event');
      window.history.replaceState({}, '', url);
    }
  };

  const saveMonitor = async (payload) => {
    setSaving(true);
    try {
      if (modal?.type === 'edit') {
        const saved = await api(`/api/monitors/${modal.monitor.id}`, { method: 'PATCH', body: JSON.stringify(payload) });
        notify('Monitor settings saved.'); setModal(null); await refresh(true);
        if (page !== 'monitor-detail') openMonitor(saved);
      } else {
        const saved = await api('/api/monitors', { method: 'POST', body: JSON.stringify(payload) });
        notify('Monitor created. Run its first check to establish a baseline.'); setModal(null); await refresh(true); openMonitor(saved);
      }
    } finally { setSaving(false); }
  };

  const checkMonitor = async (monitor) => {
    setCheckingId(monitor.id);
    const previousCheckedAt = monitor.last_checked_at;
    const startedAt = Date.now();
    try {
      await api(`/api/monitors/${monitor.id}/check`, { method: 'POST' });
      notify(`Check queued for ${monitor.name}.`);
      const pollForCompletion = async () => {
        try {
          const latest = await api(`/api/monitors/${monitor.id}`);
          await refresh(true);
          if (latest.last_checked_at && latest.last_checked_at !== previousCheckedAt) {
            setCheckingId((current) => current === monitor.id ? null : current);
            return;
          }
        } catch { /* Refresh banner handles a persistent API failure. */ }
        if (Date.now() - startedAt >= 35000) {
          setCheckingId((current) => current === monitor.id ? null : current);
          return;
        }
        window.setTimeout(pollForCompletion, 1400);
      };
      window.setTimeout(pollForCompletion, 900);
    } catch (error) {
      notify(error.message, 'error');
      setCheckingId((current) => current === monitor.id ? null : current);
    }
  };

  const deleteMonitor = async () => {
    if (modal?.type !== 'delete') return;
    setDeleting(true);
    try {
      await api(`/api/monitors/${modal.monitor.id}`, { method: 'DELETE' });
      if (selectedMonitorId === modal.monitor.id) { setSelectedMonitorId(null); setPage('monitors'); }
      setModal(null); notify('Monitor and its history deleted.'); await refresh(true);
    } catch (error) { notify(error.message, 'error'); }
    finally { setDeleting(false); }
  };

  const filteredMonitors = monitors.filter((monitor) => `${monitor.name} ${monitor.url} ${monitor.last_status}`.toLowerCase().includes(monitorSearch.toLowerCase()));
  const pageName = page === 'dashboard' ? 'Overview' : page === 'monitors' ? 'Monitored pages' : page === 'history' ? 'Change history' : page === 'settings' ? 'System settings' : 'Monitor details';

  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => setPage('dashboard')} aria-label="DeltaWatch home"><span className="brand-symbol"><ScanEye size={23} strokeWidth={1.8} /></span><span className="brand-wordmark">delta<span>watch</span><small>CHANGE INTELLIGENCE</small></span></button>
      <div className="workspace-switcher"><span className="workspace-avatar">DW</span><span className="workspace-label"><strong>My workspace</strong><small>Personal instance</small></span><ChevronDown size={14} /></div>
      <div className="sidebar-section-label">WORKSPACE</div><nav className="main-nav">{NAV.map(({ id, label, icon: Icon }) => <button className={`nav-item ${page === id || (id === 'monitors' && page === 'monitor-detail') ? 'active' : ''}`} key={id} onClick={() => setPage(id)}><Icon size={17} /><span>{label}</span>{id === 'monitors' && monitors.length > 0 && <em>{monitors.length}</em>}</button>)}</nav>
      <div className="sidebar-section-label nav-label-spaced">SYSTEM</div><button className={`nav-item ${page === 'settings' ? 'active' : ''}`} onClick={() => setPage('settings')}><Settings2 size={17} /><span>Settings & health</span></button>
      <div className="sidebar-bottom"><div className="sidebar-callout"><div className="callout-orbit"><Sparkles size={16} /></div><strong>Less noise. More signal.</strong><p>Track the changes that actually matter to you.</p><button onClick={() => setModal({ type: 'monitor' })}>Add a page <ArrowRight size={13} /></button></div><div className="sidebar-system"><span className={`system-dot ${health ? 'is-live' : ''}`} /><span>{health ? 'API connected' : 'API disconnected'}</span><button title="Refresh data" onClick={() => refresh()}><RefreshCw size={13} className={refreshing ? 'spin' : ''} /></button></div><div className="sidebar-footer">DELTAWATCH <span>v1.0.0</span></div></div>
    </aside>
    <main className="main-area"><header className="topbar"><div className="mobile-brand"><ScanEye size={21} />DeltaWatch</div><div className="breadcrumb"><span>Workspace</span><ChevronRight size={13} /><strong>{pageName}</strong></div><div className="topbar-right"><span className="top-status"><i className={`system-dot ${health ? 'is-live' : ''}`} />{health ? 'All systems operational' : 'API unavailable'}</span><button className="icon-button help-button" title="API health details" onClick={() => setPage('settings')}><CircleHelp size={16} /></button><button className="avatar-button" title="Personal workspace">M</button></div></header>
      <div className="page-content">
        {globalError && <div className="connection-banner"><AlertTriangle size={18} /><div><strong>Can't reach the backend</strong><p>{globalError}</p><small>Start FastAPI in <code>backend/</code>, then refresh this page.</small></div><Button icon={RefreshCw} size="sm" onClick={() => refresh()}>Retry</Button></div>}
        {page === 'dashboard' && <Dashboard summary={summary} monitors={monitors} events={events} onAdd={() => setModal({ type: 'monitor' })} onOpenMonitor={openMonitor} onOpenEvent={openEvent} onViewAll={() => setPage('history')} onCheck={checkMonitor} checkingId={checkingId} />}
        {page === 'monitors' && <><PageTitle eyebrow="WORKSPACE / PAGES" title="Monitored pages" subtitle="Manage what DeltaWatch watches, how often it checks, and what counts as noise."><div className="search-box"><Search size={15} /><input value={monitorSearch} onChange={(e) => setMonitorSearch(e.target.value)} placeholder="Filter pages…" aria-label="Filter monitored pages" /></div><Button variant="primary" icon={Plus} onClick={() => setModal({ type: 'monitor' })}>Add monitor</Button></PageTitle><section className="panel full-table-panel"><div className="panel-head"><div><div className="eyebrow">MONITOR INVENTORY</div><h2>All pages <span className="count-pill">{filteredMonitors.length}</span></h2></div><Button icon={RefreshCw} size="sm" onClick={() => refresh()} disabled={refreshing}>{refreshing ? 'Refreshing' : 'Refresh'}</Button></div><MonitorTable monitors={filteredMonitors} onOpen={openMonitor} onCheck={checkMonitor} onEdit={(monitor) => setModal({ type: 'edit', monitor })} onDelete={(monitor) => setModal({ type: 'delete', monitor })} checkingId={checkingId} /></section><div className="security-note"><ShieldCheck size={16} /><span>Intervals are limited to 15 minutes–24 hours to avoid hammering monitored websites.</span></div></>}
        {page === 'monitor-detail' && <MonitorDetail monitor={selectedMonitor} snapshots={snapshots} events={monitorEvents} loading={detailLoading} onBack={() => setPage('monitors')} onCheck={checkMonitor} checkingId={checkingId} onEdit={(monitor) => setModal({ type: 'edit', monitor })} onDelete={(monitor) => setModal({ type: 'delete', monitor })} onOpenEvent={openEvent} />}
        {page === 'history' && <HistoryPage events={events} monitors={monitors} onOpenEvent={openEvent} search={search} setSearch={setSearch} />}
        {page === 'settings' && <SettingsPage health={health} summary={summary} onRefresh={() => refresh()} />}
      </div>
      <footer className="main-footer"><span>DELTAWATCH · CHANGE INTELLIGENCE</span><span>Built for signal, engineered for reliability.</span><span><span className={`system-dot ${health ? 'is-live' : ''}`} /> {health ? 'Connected' : 'Disconnected'}</span></footer>
    </main>
    {modal?.type === 'monitor' && <Modal title="Add a monitored page" eyebrow="NEW MONITOR" onClose={() => setModal(null)}><MonitorForm onSave={saveMonitor} onClose={() => setModal(null)} saving={saving} /></Modal>}
    {modal?.type === 'edit' && <Modal title="Tune your monitor" eyebrow="MONITOR SETTINGS" onClose={() => setModal(null)}><MonitorForm initial={modal.monitor} onSave={saveMonitor} onClose={() => setModal(null)} saving={saving} /></Modal>}
    {modal?.type === 'delete' && <ConfirmDelete monitor={modal.monitor} onCancel={() => setModal(null)} onConfirm={deleteMonitor} busy={deleting} />}
    {eventToView && <EventModal event={eventToView} onClose={closeEvent} />}
    {toast && <div className={`toast toast-${toast.type}`} role="status"><span className="toast-icon">{toast.type === 'error' ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}</span>{toast.message}<button onClick={() => setToast(null)} aria-label="Dismiss notification"><X size={14} /></button></div>}
  </div>;
}
