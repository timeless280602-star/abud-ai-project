import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity, AlertTriangle, ArrowUpRight, AudioWaveform, Bot,
  BrainCircuit, ChevronDown, ChevronRight, CircleDot, Command,
  Cpu, Database, Fingerprint, Gauge, Globe, HardDrive, Hexagon,
  LayoutDashboard, LockKeyhole, LogOut, Menu, Network, Radio,
  RefreshCw, Server, Settings, Shield, ShieldCheck, Terminal,
  Users, Wifi, X, Zap, Search, Plus, Pencil, Trash2, Save, Globe2, Archive, ArchiveRestore
} from 'lucide-react';
import './style.css';
const WebChat = React.lazy(() => import('./WebChat'));

const modules = [
  { id: 'chat', label: 'AI Chat', group: 'MAIN', icon: Bot },
  { id: 'overview', label: 'Command Center', group: 'MAIN', icon: LayoutDashboard },
  { id: 'neural', label: 'Neural Engine', group: 'INTELLIGENCE', icon: BrainCircuit },
  { id: 'memory', label: 'Memory Matrix', group: 'INTELLIGENCE', icon: Database },
  { id: 'network', label: 'Network Command', group: 'INFRASTRUCTURE', icon: Network },
  { id: 'security', label: 'Security Protocol', group: 'INFRASTRUCTURE', icon: Shield },
  { id: 'automation', label: 'Automation Engine', group: 'OPERATIONS', icon: AudioWaveform },
  { id: 'knowledge', label: 'Knowledge Archives', group: 'OPERATIONS', icon: HardDrive },
  { id: 'logs', label: 'Activity Logs', group: 'OPERATIONS', icon: Terminal },
  { id: 'integrations', label: 'Integrasi', group: 'ACCOUNT', icon: Plus },
  { id: 'settings', label: 'Core Settings', group: 'SYSTEM', icon: Settings }
];

const MEMORY_SOURCE_LABELS = {
  unknown: 'Unknown origin',
  direct: 'Direct request',
  tool: 'Assistant tool',
  auto: 'Auto-saved',
  dashboard: 'Dashboard'
};

const MANAGE_IMPLIES_VIEW = {
  'memory.personal.manage': 'memory.personal.view',
  'memory.guild.manage': 'memory.guild.view',
  'ai_config.manage': 'ai_config.view',
  'server.manage': 'server.view',
  'knowledge_base.manage': 'knowledge_base.view',
  'automation.manage': 'automation.view'
};

function permissionHas(user, permission, scopeType = null, scopeId = null) {
  if (user?.is_creator) return true;

  const grants = user?.permissions || [];
  return grants.some(grant => {
    if (scopeType && grant.scope_type !== scopeType) return false;
    if (scopeId && String(grant.scope_id) !== String(scopeId)) return false;

    return grant.permission === permission ||
      MANAGE_IMPLIES_VIEW[grant.permission] === permission;
  });
}

function hasAnyPermission(user, permission) {
  if (user?.is_creator) return true;
  return (user?.permissions || []).some(grant =>
    grant.permission === permission ||
    MANAGE_IMPLIES_VIEW[grant.permission] === permission
  );
}

function canOpenModule(user, moduleId) {
  if (moduleId === 'chat' || moduleId === 'integrations') return true;
  if (!user?.dashboard_access) return false;
  if (moduleId === 'overview') return true;
  if (user?.is_creator) return true;

  const requirements = {
    neural: 'ai_config.view',
    memory: 'memory.personal.view',
    network: 'server.view',
    security: 'permissions.delegate',
    automation: 'automation.view',
    knowledge: 'knowledge_base.view',
    logs: 'activity_logs.view',
    settings: 'system_settings.view'
  };

  if (moduleId === 'memory') {
    return hasAnyPermission(user, 'memory.personal.view') ||
      hasAnyPermission(user, 'memory.guild.view');
  }

  const required = requirements[moduleId];
  return required ? hasAnyPermission(user, required) : false;
}

async function api(path, options = {}) {
  const isForm = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body && !isForm ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers
    }
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {}
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function Brand({ compact = false }) {
  return (
    <div className="brand">
      <div className="brand-mark"><Hexagon size={25} strokeWidth={1.7}/><span>A</span></div>
      {!compact && <div><div className="brand-name">ABUD<span>.</span></div><div className="brand-sub">TACTICAL INTELLIGENCE</div></div>}
    </div>
  );
}

function CoreReactor({ status = 'ONLINE' }) {
  return (
    <div className="reactor-wrap">
      <div className="reactor-glow"/>
      <div className="reactor-ring ring-one"/>
      <div className="reactor-ring ring-two"/>
      <div className="reactor-ring ring-three"/>
      <div className="reactor-cross cross-one"/>
      <div className="reactor-cross cross-two"/>
      <div className="reactor-core">
        <div className="core-inner"><Hexagon size={47} strokeWidth={1.1}/><span>A</span></div>
      </div>
      <div className="reactor-label"><span className="pulse-dot"/> {status}</div>
      <div className="reactor-coord coord-a">CORE / 001</div>
      <div className="reactor-coord coord-b">NEURAL MATRIX</div>
    </div>
  );
}

function Login({ error }) {
  const [mode, setMode] = useState('oauth');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState('');

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setLocalError('');
    try {
      await api('/auth/password/login', {
        method: 'POST',
        body: JSON.stringify({ username, password, remember_me: remember })
      });
      window.location.reload();
    } catch (err) {
      setLocalError(err.message || 'Login gagal.');
    } finally {
      setBusy(false);
    }
  }

  const rememberParam = remember ? '1' : '0';

  return (
    <main className="login-screen">
      <div className="login-grid"/>
      <div className="login-top"><Brand/><span className="system-code">SECURE ACCESS // AUTH GATEWAY 01</span></div>
      <div className="login-center">
        <div className="login-reactor"><CoreReactor status="AWAITING AUTH"/></div>
        <div className="eyebrow"><span className="pulse-dot"/> CENTRAL INTELLIGENCE SYSTEM</div>
        <h1>CONTROL<br/><span>THE CORE.</span></h1>
        <p className="login-description">Unified command interface for Abud's intelligence, memory and network infrastructure.</p>
        <div className="login-panel">
          <div className="panel-heading"><LockKeyhole size={15}/> AUTHENTICATED ACCESS <span>ENCRYPTED</span></div>
          {(error || localError) && <div className="error-line"><AlertTriangle size={14}/>{localError || error}</div>}
          {mode === 'oauth' ? <>
            <a className="login-button discord" href={`/auth/discord/login?remember=${rememberParam}`}>
              <span className="login-provider discord-provider">
                <svg viewBox="0 0 24 24" role="img" aria-label="Discord"><path fill="currentColor" d="M19.73 5.36A19.3 19.3 0 0 0 14.96 3.9l-.58 1.18a17.8 17.8 0 0 0-4.76 0L9.04 3.9a19.3 19.3 0 0 0-4.77 1.46C1.25 9.8.43 14.14.84 18.42a19.4 19.4 0 0 0 5.85 2.96l1.27-2.07c-.7-.26-1.36-.59-1.98-.97l.48-.38c3.82 1.78 7.97 1.78 11.74 0l.49.38c-.63.38-1.29.71-1.99.97l1.27 2.07a19.4 19.4 0 0 0 5.85-2.96c.49-4.96-.84-9.26-4.09-13.06ZM8.55 14.98c-1.14 0-2.08-1.05-2.08-2.34s.91-2.34 2.08-2.34 2.1 1.06 2.08 2.34c0 1.29-.92 2.34-2.08 2.34Zm6.9 0c-1.14 0-2.08-1.05-2.08-2.34s.91-2.34 2.08-2.34 2.1 1.06 2.08 2.34c0 1.29-.91 2.34-2.08 2.34Z"/></svg>
              </span><span>CONTINUE WITH DISCORD</span><ArrowUpRight size={16}/>
            </a>
            <a className="login-button google" href={`/auth/google/login?remember=${rememberParam}`}>
              <span className="login-provider google-provider">
                <svg viewBox="0 0 48 48" role="img" aria-label="Google"><path fill="#4285F4" d="M43.6 24.5c0-1.4-.1-2.8-.4-4.1H24v7.8h11a9.4 9.4 0 0 1-4.1 6.2v5.1h6.6c3.9-3.6 6.1-8.8 6.1-15Z"/><path fill="#34A853" d="M24 44c5.5 0 10.1-1.8 13.5-4.9l-6.6-5.1c-1.8 1.2-4.1 2-6.9 2-5.3 0-9.8-3.6-11.4-8.4H5.8v5.3A20 20 0 0 0 24 44Z"/><path fill="#FBBC05" d="M12.6 27.6a12 12 0 0 1 0-7.2v-5.3H5.8a20 20 0 0 0 0 17.8l6.8-5.3Z"/><path fill="#EA4335" d="M24 12c3 0 5.7 1 7.8 3.1l5.8-5.8C34.1 5.9 29.5 4 24 4A20 20 0 0 0 5.8 15.1l6.8 5.3C14.2 15.6 18.7 12 24 12Z"/></svg>
              </span><span>CONTINUE WITH GOOGLE</span><ArrowUpRight size={16}/>
            </a>
            <button className="auth-switch" onClick={() => setMode('password')}>LOGIN DENGAN USERNAME & PASSWORD</button>
          </> : <>
            <form onSubmit={submit} className="auth-form">
              <label>USERNAME</label>
              <input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} minLength={3} maxLength={24} required placeholder="Username"/>
              <label>PASSWORD</label>
              <input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required placeholder="Password"/>
              <button className="login-submit" disabled={busy}>{busy ? 'AUTHENTICATING...' : 'SIGN IN'} <ArrowUpRight size={15}/></button>
            </form>
            <button className="auth-switch" onClick={() => setMode('oauth')}>KEMBALI KE LOGIN DISCORD / GOOGLE</button>
          </>}
          <label className="remember-row"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)}/> <span>Ingat saya di perangkat ini</span></label>
          <div className="login-foot"><ShieldCheck size={13}/> Identity verification enabled <span>•</span> Session protected</div>
        </div>
      </div>
      <div className="login-bottom"><span>ABUD CONTROL CENTER // V1.0</span><span>AUTHORIZED PERSONNEL ONLY</span><span>INDONESIA // UTC+7</span></div>
    </main>
  );
}

function ProfileSetup() {
  const [mode, setMode] = useState('register');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [avatar, setAvatar] = useState(null);
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const rememberParam = remember ? '1' : '0';

  async function submit(e) {
    e.preventDefault();
    setError('');
    if (avatar && avatar.size > 1024 * 1024) {
      return setError('Foto profil maksimal 1 MB.');
    }
    if (password.length < 12) return setError('Password minimal 12 karakter.');
    if (password !== confirm) return setError('Konfirmasi password tidak cocok.');

    setBusy(true);
    const data = new FormData();
    data.append('username', username);
    data.append('password', password);
    if (avatar) data.append('avatar', avatar);

    try {
      await api('/auth/profile/setup', { method: 'POST', body: data });
      window.location.reload();
    } catch (err) {
      setError(err.message || 'Pembuatan akun gagal.');
    } finally {
      setBusy(false);
    }
  }

  async function signIn(e) {
    e.preventDefault();
    setError('');
    setBusy(true);

    try {
      await api('/auth/password/login', {
        method: 'POST',
        body: JSON.stringify({
          username,
          password,
          remember_me: remember
        })
      });
      window.location.reload();
    } catch (err) {
      setError(err.message || 'Login gagal.');
    } finally {
      setBusy(false);
    }
  }

  function switchMode(nextMode) {
    setError('');
    setMode(nextMode);
    setPassword('');
    setConfirm('');
  }

  return (
    <main className="login-screen">
      <div className="login-grid"/>
      <div className="login-top"><Brand/><span className="system-code">IDENTITY INITIALIZATION // STEP 02</span></div>
      <div className="login-center">
        <div className="eyebrow"><span className="pulse-dot"/> {mode === 'register' ? 'ACCOUNT REGISTRATION' : 'ACCOUNT SIGN IN'}</div>
        <h1>{mode === 'register' ? <>CREATE<br/><span>YOUR ID.</span></> : <>WELCOME<br/><span>BACK.</span></>}</h1>
        <p className="login-description">
          {mode === 'register'
            ? 'Autentikasi berhasil. Buat username dan password ABUD untuk login berikutnya.'
            : 'Masuk menggunakan username dan password ABUD yang sudah kamu buat sebelumnya.'}
        </p>
        <div className="login-panel">
          <div className="panel-heading">
            <Fingerprint size={15}/>
            {mode === 'register' ? 'OPERATOR PROFILE' : 'OPERATOR SIGN IN'}
            <span>{mode === 'register' ? 'REQUIRED' : 'SECURE'}</span>
          </div>

          {error && <div className="error-line"><AlertTriangle size={14}/>{error}</div>}

          {mode === 'register' ? (
            <form className="auth-form" onSubmit={submit}>
              <label>USERNAME</label>
              <input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} minLength={3} maxLength={24} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{2,23}" required placeholder="3–24 karakter"/>
              <label>PASSWORD</label>
              <input type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} minLength={12} maxLength={128} required placeholder="Minimal 12 karakter"/>
              <label>CONFIRM PASSWORD</label>
              <input type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} required placeholder="Ulangi password"/>
              <label>PROFILE PHOTO <span className="optional-label">OPTIONAL</span></label>
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setAvatar(e.target.files?.[0] || null)}/>
              <small className="form-hint">PNG, JPG, WebP · Maksimal 1 MB</small>
              <button className="login-submit" disabled={busy}>{busy ? 'CREATING ACCOUNT...' : 'CREATE ABUD ACCOUNT'} <ArrowUpRight size={15}/></button>
            </form>
          ) : (
            <>
              <div className="profile-oauth">
                <a className="login-button discord" href={`/auth/discord/login?remember=${rememberParam}`}>
                  <span className="login-provider discord-provider">
                    <svg viewBox="0 0 24 24" role="img" aria-label="Discord">
                      <path fill="currentColor" d="M19.73 5.36A19.3 19.3 0 0 0 14.96 3.9l-.58 1.18a17.8 17.8 0 0 0-4.76 0L9.04 3.9a19.3 19.3 0 0 0-4.77 1.46C1.25 9.8.43 14.14.84 18.42a19.4 19.4 0 0 0 5.85 2.96l1.27-2.07c-.7-.26-1.36-.59-1.98-.97l.48-.38c3.82 1.78 7.97 1.78 11.74 0l.49.38c-.63.38-1.29.71-1.99.97l1.27 2.07a19.4 19.4 0 0 0 5.85-2.96c.49-4.96-.84-9.26-4.09-13.06ZM8.55 14.98c-1.14 0-2.08-1.05-2.08-2.34s.91-2.34 2.08-2.34 2.1 1.06 2.08 2.34c0 1.29-.92 2.34-2.08 2.34Zm6.9 0c-1.14 0-2.08-1.05-2.08-2.34s.91-2.34 2.08-2.34 2.1 1.06 2.08 2.34c0 1.29-.91 2.34-2.08 2.34Z"/>
                    </svg>
                  </span>
                  <span>CONTINUE WITH DISCORD</span>
                  <ArrowUpRight size={16}/>
                </a>

                <a className="login-button google" href={`/auth/google/login?remember=${rememberParam}`}>
                  <span className="login-provider google-provider">
                    <svg viewBox="0 0 48 48" role="img" aria-label="Google">
                      <path fill="#4285F4" d="M43.6 24.5c0-1.4-.1-2.8-.4-4.1H24v7.8h11a9.4 9.4 0 0 1-4.1 6.2v5.1h6.6c3.9-3.6 6.1-8.8 6.1-15Z"/>
                      <path fill="#34A853" d="M24 44c5.5 0 10.1-1.8 13.5-4.9l-6.6-5.1c-1.8 1.2-4.1 2-6.9 2-5.3 0-9.8-3.6-11.4-8.4H5.8v5.3A20 20 0 0 0 24 44Z"/>
                      <path fill="#FBBC05" d="M12.6 27.6a12 12 0 0 1 0-7.2v-5.3H5.8a20 20 0 0 0 0 17.8l6.8-5.3Z"/>
                      <path fill="#EA4335" d="M24 12c3 0 5.7 1 7.8 3.1l5.8-5.8C34.1 5.9 29.5 4 24 4A20 20 0 0 0 5.8 15.1l6.8 5.3C14.2 15.6 18.7 12 24 12Z"/>
                    </svg>
                  </span>
                  <span>CONTINUE WITH GOOGLE</span>
                  <ArrowUpRight size={16}/>
                </a>
              </div>

              <div className="profile-auth-divider">OR SIGN IN WITH USERNAME</div>

              <form className="auth-form" onSubmit={signIn}>
              <label>USERNAME</label>
              <input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} minLength={3} maxLength={24} required placeholder="Username ABUD"/>
              <label>PASSWORD</label>
              <input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} maxLength={128} required placeholder="Password ABUD"/>
              <label className="remember-row">
                <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)}/>
                <span>Ingat saya di perangkat ini</span>
              </label>
              <button className="login-submit" disabled={busy}>{busy ? 'AUTHENTICATING...' : 'SIGN IN'} <ArrowUpRight size={15}/></button>
            </form>
            </>
          )}

          <button
            type="button"
            className="auth-switch"
            disabled={busy}
            onClick={() => switchMode(mode === 'register' ? 'signin' : 'register')}
          >
            {mode === 'register'
              ? 'SUDAH PUNYA AKUN? SIGN IN'
              : 'BELUM PUNYA AKUN? CREATE ACCOUNT'}
          </button>

          <div className="login-foot"><ShieldCheck size={13}/>{mode === 'register' ? 'Password disimpan dalam bentuk hash, bukan plaintext' : 'Secure username and password authentication'}</div>
        </div>
      </div>
      <div className="login-bottom"><span>ABUD CONTROL CENTER // V1.0</span><span>{mode === 'register' ? 'PROFILE SETUP REQUIRED' : 'SECURE ACCOUNT ACCESS'}</span><span>INDONESIA // UTC+7</span></div>
    </main>
  );
}
function Metric({ icon: Icon, label, value, detail, state }) {
  return (
    <div className="metric-card">
      <div className="metric-top"><span>{label}</span><Icon size={17}/></div>
      <div className="metric-value">{value}</div>
      <div className="metric-bottom"><span className={state === 'bad' ? 'red-text' : 'green-text'}><i className="tiny-dot"/> {detail}</span><span className="metric-live">LIVE</span></div>
    </div>
  );
}

function Overview({ health, guilds, refresh, refreshing, user }) {
  const online = health?.status === 'healthy';
  return (
    <div className="page-content cockpit">
      <div className="cockpit-heading">
        <div>
          <div className="eyebrow"><span className="pulse-dot"/> ABUD INTELLIGENCE / COMMAND INTERFACE</div>
          <h1>Command <span>Center.</span></h1>
          <p>Unified intelligence, infrastructure and operational awareness.</p>
        </div>
        <button className="outline-button" onClick={refresh} disabled={refreshing}>
          <RefreshCw size={14} className={refreshing ? 'spin' : ''}/> SYNC SYSTEM
        </button>
      </div>

      <section className="cockpit-hero">
        <div className="cockpit-copy">
          <div className="cockpit-kicker">01 / CENTRAL INTELLIGENCE CORE</div>
          <div className="cockpit-live"><i/> {online ? 'CORE SYSTEM ONLINE' : 'CORE CONNECTION UNAVAILABLE'}</div>
          <h2>BEYOND<br/><span>INTELLIGENCE.</span></h2>
          <p>ABUD unified tactical intelligence platform. All operational indicators are derived from authenticated live services.</p>
          <div className="cockpit-tags">
            <span><CircleDot size={12}/> {online ? 'API CONNECTED' : 'API OFFLINE'}</span>
            <span><ShieldCheck size={12}/> {user.is_creator ? 'ROOT AUTHORITY' : 'AUTHORIZED SESSION'}</span>
          </div>
        </div>
        <div className="cockpit-visual">
          <div className="visual-orbit orbit-a"/><div className="visual-orbit orbit-b"/>
          <video autoPlay muted loop playsInline preload="metadata"
            poster="https://vgbujcuwptvheqijyjbe.supabase.co/storage/v1/object/public/hmac-uploads/projects/09044fce-556b-48ec-89f9-d46f4d06f6ce/generated-images/generated-b2f9cce9-392e-43be-b217-09f9de7c7f05.jpg"
            src="https://vgbujcuwptvheqijyjbe.supabase.co/storage/v1/object/public/hmac-uploads/generations/b39efcf8-6d3d-48b0-94ff-bb008796c88f/output.mp4"/>
          <div className="visual-label"><span>ABUD / CORE-01</span><b>NEURAL REACTOR</b></div>
          <div className="visual-coordinate">CORE FREQUENCY // ACTIVE</div>
        </div>
        <div className="cockpit-index">ABUD <b>001</b> / TACTICAL SYSTEM</div>
      </section>

      <div className="cockpit-section-title"><span>02 / OPERATIONAL TELEMETRY</span><span>LIVE AUTHENTICATED DATA</span></div>
      <div className="metrics-grid cockpit-metrics">
        <Metric icon={Activity} label="API STATUS" value={online ? 'ONLINE' : 'OFFLINE'} detail={online ? 'HEALTHY RESPONSE' : 'NO RESPONSE'} state={online ? 'good' : 'bad'}/>
        <Metric icon={Network} label="NETWORK NODES" value={guilds.length.toString().padStart(2,'0')} detail="VERIFIED GUILDS"/>
        <Metric icon={Fingerprint} label="IDENTITY" value={user.is_creator ? 'CREATOR' : 'VERIFIED'} detail={user.discord_linked ? 'DISCORD LINKED' : 'GOOGLE SESSION'}/>
        <Metric icon={ShieldCheck} label="PERMISSIONS" value={String(user.permissions?.length || 0).padStart(2,'0')} detail="ACTIVE GRANTS"/>
      </div>

      <div className="cockpit-section-title"><span>03 / INTELLIGENCE NETWORK</span><span>AUTHORIZED ENTITIES</span></div>
      <div className="content-grid cockpit-lower">
        <section className="data-panel">
          <div className="panel-title"><span><Server size={15}/> CONNECTED NETWORK NODES</span><span className="panel-count">{guilds.length} VERIFIED</span></div>
          {guilds.length ? guilds.map(g => (
            <div className="guild-row" key={g.guild_id}>
              <div className="guild-icon">{user.avatar_url ? <img src={user.avatar_url} alt="Profile"/> : <Users size={17}/>}</div>
              <div className="guild-info"><strong>{g.guild_name || 'Discord Server'}</strong><small>{g.is_owner ? 'SERVER OWNER' : g.is_admin ? 'ADMINISTRATOR' : 'MEMBER'} // {g.guild_id}</small></div>
              <span className="node-status"><i/> VERIFIED</span><ChevronRight size={15}/>
            </div>
          )) : <div className="empty-state"><Network size={23}/><strong>No accessible network nodes</strong><span>Verified Discord server access will appear here.</span></div>}
        </section>
        <section className="data-panel cockpit-identity">
          <div className="panel-title"><span><Fingerprint size={15}/> OPERATOR IDENTITY</span><span className="panel-count">SESSION VERIFIED</span></div>
          <div className="profile-block">
            <div className="avatar-core">{user.avatar_url ? <img src={user.avatar_url} alt="Profile"/> : (user.display_name || 'A').slice(0,1).toUpperCase()}</div>
            <div><strong>{user.display_name || 'Abud Operator'}</strong><small>{user.email || 'Verified identity'}</small></div>
          </div>
          <div className="profile-line"><span>CREATOR AUTHORITY</span><strong>{user.is_creator ? 'GRANTED' : 'NOT GRANTED'}</strong></div>
          <div className="profile-line"><span>DISCORD LINKED</span><strong>{user.discord_linked ? 'YES' : 'NO'}</strong></div>
          <div className="profile-line"><span>ACTIVE PERMISSIONS</span><strong>{user.permissions?.length || 0}</strong></div>
        </section>
      </div>
      <div className="footer-note"><span>ABUD TACTICAL INTELLIGENCE SYSTEM</span><span>TELEMETRY: LIVE API / AUTH SERVICE</span></div>
    </div>
  );
}

function MemoryMatrix({ user, guilds }) {
  const accessibleGuilds = guilds.filter(g => {
    const grants = g.permissions || [];
    return grants.includes('memory.guild.view') ||
      grants.includes('memory.guild.manage');
  });

  const personalView = permissionHas(user, 'memory.personal.view', 'global', '*');
  const personalManage = permissionHas(user, 'memory.personal.manage', 'global', '*');
  const initialScope = personalView ? 'personal' :
    accessibleGuilds.length ? 'guild' : 'global';

  const [scope, setScope] = useState(initialScope);
  const [selectedGuild, setSelectedGuild] = useState(
    accessibleGuilds.length ? String(accessibleGuilds[0].guild_id) : ''
  );
  const [items, setItems] = useState([]);
  const [query, setQuery] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [draft, setDraft] = useState('');
  const [category, setCategory] = useState('general');
  const [editingId, setEditingId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [review, setReview] = useState(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const reviewKey = JSON.stringify([scope, selectedGuild, draft, category, editingId, showArchived]);
  const currentReview = review?.key === reviewKey ? review.data : null;

  const activeGuild = accessibleGuilds.find(
    g => String(g.guild_id) === String(selectedGuild)
  );

  const guildView = Boolean(activeGuild);
  const guildManage = Boolean(
    activeGuild?.permissions?.includes('memory.guild.manage')
  );

  const canView = scope === 'personal'
    ? personalView
    : scope === 'guild'
      ? guildView
      : Boolean(user.is_creator);

  const canManage = scope === 'personal'
    ? personalManage
    : scope === 'guild'
      ? guildManage
      : Boolean(user.is_creator);

  useEffect(() => {
    if (scope === 'guild' && !selectedGuild && accessibleGuilds.length) {
      setSelectedGuild(String(accessibleGuilds[0].guild_id));
    }
  }, [scope, selectedGuild, accessibleGuilds]);

  useEffect(() => {
    if (!canView || (scope === 'guild' && !selectedGuild)) {
      setItems([]);
      setBusy(false);
      return;
    }

    let alive = true;
    const params = new URLSearchParams({ scope, q: query, archived: String(showArchived) });
    if (scope === 'guild') params.set('guild_id', selectedGuild);

    setBusy(true);
    setError('');

    api(`/dashboard/memory?${params.toString()}`)
      .then(result => {
        if (alive) setItems(result.items || []);
      })
      .catch(e => {
        if (alive) {
          setItems([]);
          setError(e.message || 'Gagal memuat Memory.');
        }
      })
      .finally(() => {
        if (alive) setBusy(false);
      });

    return () => { alive = false; };
  }, [scope, selectedGuild, query, reload, canView, showArchived]);

  function changeScope(next) {
    setScope(next);
    setItems([]);
    setReview(null);
    setDraft('');
    setEditingId(null);
    setNotice('');
    setError('');
  }

  async function submitMemory(event) {
    event.preventDefault();
    if (!draft.trim()) return;

    setBusy(true);
    setError('');
    setNotice('');

    const payload = {
      scope,
      guild_id: scope === 'guild' ? selectedGuild : null,
      content: draft.trim(),
      category: scope === 'global' ? category : 'general'
    };

    try {
      await api('/dashboard/memory', {
        method: editingId ? 'PUT' : 'POST',
        body: JSON.stringify(editingId ? { ...payload, memory_id: editingId } : payload)
      });
      setDraft('');
      setEditingId(null);
      setNotice(editingId ? 'Memory berhasil diperbarui.' : 'Memory berhasil disimpan.');
      setReload(v => v + 1);
    } catch (e) {
      setError(e.message || 'Gagal menyimpan Memory.');
    } finally {
      setBusy(false);
    }
  }

  async function checkSimilar(useAI) {
    const key = reviewKey;
    setReviewBusy(true);
    setError('');
    try {
      const data = await api('/dashboard/memory/similar', {
        method: 'POST',
        body: JSON.stringify({
          scope, guild_id: scope === 'guild' ? selectedGuild : null,
          content: draft.trim(), category,
          exclude_memory_id: editingId, use_ai: useAI
        })
      });
      setReview({ key, data });
    } catch (e) {
      setReview({ key, data: { items: [], error: e.message || 'Review unavailable.' } });
    } finally {
      setReviewBusy(false);
    }
  }

  function useCandidate(item, combine) {
    setEditingId(item.id);
    setDraft(combine ? `${item.content}\n${draft}` : draft);
    setCategory(item.category || 'general');
    setNotice('Review the draft, then save to update this record. No record has been changed or deleted.');
    setReview(null);
  }

  function startEdit(item) {
    setEditingId(item.id);
    setDraft(item.content || '');
    setCategory(item.category || 'general');
    setNotice('');
    setError('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function changeArchive(item) {
    const archive = !showArchived;
    if (archive && !window.confirm('Archive this memory? It will leave active memory and can be restored from the archive.')) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await api('/dashboard/memory/archive', {
        method: 'POST',
        body: JSON.stringify({ scope, guild_id: scope === 'guild' ? selectedGuild : null,
          memory_id: item.id, archived: archive })
      });
      setItems([]);
      setDraft('');
      setEditingId(null);
      setReview(null);
      setNotice(archive ? 'Memory archived. Restore it from the archive when needed.' : 'Memory restored to active memory.');
      setReload(v => v + 1);
    } catch (e) {
      setError(e.message || 'Unable to change archive status.');
    } finally {
      setBusy(false);
    }
  }

  async function deleteMemory(item) {
    if (!window.confirm('Hapus Memory ini secara permanen?')) return;

    setBusy(true);
    setError('');
    setNotice('');

    try {
      await api('/dashboard/memory', {
        method: 'DELETE',
        body: JSON.stringify({
          scope,
          guild_id: scope === 'guild' ? selectedGuild : null,
          memory_id: item.id
        })
      });
      setNotice('Memory berhasil dihapus.');
      if (editingId === item.id) {
        setEditingId(null);
        setDraft('');
      }
      setReload(v => v + 1);
    } catch (e) {
      setError(e.message || 'Gagal menghapus Memory.');
    } finally {
      setBusy(false);
    }
  }

  const title = scope === 'personal'
    ? 'PERSONAL MEMORY'
    : scope === 'guild'
      ? 'GUILD MEMORY'
      : 'GLOBAL MEMORY';

  return (
    <div className="page-content memory-matrix">
      <div className="page-heading">
        <div>
          <div className="eyebrow">INTELLIGENCE / MEMORY MATRIX</div>
          <h1>MEMORY <span>MATRIX.</span></h1>
          <p>Manage persistent knowledge with identity and scope-based access control.</p>
        </div>
        <button className="outline-button" onClick={() => setReload(v => v + 1)} disabled={busy}>
          <RefreshCw size={14} className={busy ? 'spin' : ''}/> REFRESH
        </button>
      </div>

      <div className="memory-scope-tabs">
        {personalView && (
          <button className={scope === 'personal' ? 'active' : ''} onClick={() => changeScope('personal')}>
            <Fingerprint size={15}/> PERSONAL
          </button>
        )}
        {accessibleGuilds.length > 0 && (
          <button className={scope === 'guild' ? 'active' : ''} onClick={() => changeScope('guild')}>
            <Users size={15}/> GUILD
          </button>
        )}
        {user.is_creator && (
          <button className={scope === 'global' ? 'active' : ''} onClick={() => changeScope('global')}>
            <Globe2 size={15}/> GLOBAL
          </button>
        )}
      </div>

      <section className="memory-toolbar data-panel">
        <div className="panel-title">
          <span><Database size={15}/> {title}</span>
          <span className="panel-count">{items.length} RECORDS</span>
        </div>
        <div className="memory-toolbar-body">
          {scope === 'guild' && (
            <label className="memory-field guild-select-field">
              <span>DISCORD SERVER</span>
              <select value={selectedGuild} onChange={e => { setSelectedGuild(e.target.value); setItems([]); setEditingId(null); setDraft(''); setReview(null); }}>
                {!accessibleGuilds.length && <option value="">No authorized servers</option>}
                {accessibleGuilds.map(g => (
                  <option key={g.guild_id} value={g.guild_id}>{g.guild_name || g.guild_id}</option>
                ))}
              </select>
            </label>
          )}
          <label className="memory-archive-toggle">
            <input type="checkbox" checked={showArchived} disabled={busy} onChange={e => {
              setShowArchived(e.target.checked);setItems([]);setDraft('');setEditingId(null);setReview(null);setNotice('');
            }}/>
            Show archived memories
          </label>
          <label className="memory-search">
            <Search size={15}/>
            <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search stored memories..."/>
          </label>
        </div>
        {scope === 'guild' && activeGuild && (
          <div className="memory-access-note">
            <ShieldCheck size={14}/>
            {guildManage ? 'EXPLICIT GUILD MEMORY MANAGE' : 'EXPLICIT GUILD MEMORY VIEW'}
          </div>
        )}
      </section>

      {error && <div className="memory-message memory-error"><AlertTriangle size={14}/>{error}</div>}
      {notice && <div className="memory-message memory-success"><ShieldCheck size={14}/>{notice}</div>}

      {!canView && (
        <div className="empty-state">
          <Shield size={25}/>
          <strong>No memory access assigned</strong>
          <span>This identity has no view permission for the selected scope.</span>
        </div>
      )}

      {canManage && !showArchived && (
        <form className="memory-editor data-panel" onSubmit={submitMemory}>
          <div className="panel-title">
            <span><Plus size={15}/>{editingId ? 'EDIT MEMORY RECORD' : 'CREATE MEMORY RECORD'}</span>
            <span className="panel-count">{scope.toUpperCase()} SCOPE</span>
          </div>
          {scope === 'global' && (
            <label className="memory-field">
              <span>CATEGORY</span>
              <input value={category} maxLength={64} onChange={e => setCategory(e.target.value)} placeholder="general"/>
            </label>
          )}
          <label className="memory-field">
            <span>MEMORY CONTENT</span>
            <textarea value={draft} onChange={e => setDraft(e.target.value)} maxLength={1000} rows={4} placeholder="Enter information Abud should retain..." required/>
            <small>{draft.length}/1000 CHARACTERS</small>
          </label>
          <div className="memory-editor-actions">
            <button type="button" className="outline-button" onClick={() => checkSimilar(false)} disabled={busy || reviewBusy || !draft.trim() || draft.length > 1000}>
              CHECK SIMILAR WORDING
            </button>
            <button type="button" className="outline-button" onClick={() => checkSimilar(true)} disabled={busy || reviewBusy || !draft.trim() || draft.length > 1000}>
              {reviewBusy ? 'REVIEWING...' : 'REVIEW MEANING WITH AI'}
            </button>
          </div>
          <small className="memory-review-disclosure">AI review sends this draft and up to five memories from this scope to your configured AI service. Suggestions never change records.</small>
          {draft.length > 1000 && <p className="memory-error">Shorten the combined draft to 1000 characters before saving.</p>}
          {currentReview && (
            <section className="memory-review" aria-label="Similar memory suggestions" aria-live="polite">
              <h3>REVIEW SIMILAR MEMORIES</h3>
              {currentReview.error && <p>{currentReview.error}</p>}
              {['not_configured', 'unavailable'].includes(currentReview.ai_status) && <p>AI review unavailable. Wording matches are shown below.</p>}
              {!currentReview.error && !currentReview.items.length && <p>No candidates found by this review. Other memories may still describe the same fact.</p>}
              {currentReview.items.map(item => (
                <article className="memory-review-candidate" key={item.id}>
                  <strong>RECORD #{item.id}</strong>
                  <p>{item.content}</p>
                  <small>{item.reason}</small>
                  {item.ai_relation && <p>AI suggestion: {item.ai_relation} — {item.ai_reason}</p>}
                  <div className="memory-editor-actions">
                    <button type="button" className="outline-button" onClick={() => useCandidate(item, false)} disabled={busy}>UPDATE THIS RECORD</button>
                    <button type="button" className="outline-button" onClick={() => useCandidate(item, true)} disabled={busy}>COMBINE INTO DRAFT</button>
                  </div>
                </article>
              ))}
              <button type="button" className="outline-button" disabled={busy} onClick={() => {setEditingId(null);setReview(null);setNotice('Kept as a separate draft. Save when ready; identical text still uses existing deduplication.');}}>KEEP AS SEPARATE DRAFT</button>
            </section>
          )}
          <div className="memory-editor-actions">
            {editingId && (
              <button type="button" className="outline-button" onClick={() => {setEditingId(null);setDraft('');}}>
                <X size={14}/> CANCEL
              </button>
            )}
            <button type="submit" className="memory-primary-button" disabled={busy || reviewBusy || !draft.trim() || draft.length > 1000 || (scope === 'guild' && !selectedGuild)}>
              <Save size={14}/> {busy ? 'PROCESSING...' : editingId ? 'UPDATE MEMORY' : 'SAVE MEMORY'}
            </button>
          </div>
        </form>
      )}

      <section className="memory-records data-panel">
        <div className="panel-title">
          <span><HardDrive size={15}/> STORED RECORDS</span>
          <span className="panel-count">{busy ? 'SYNCING' : `${items.length} LOADED`}</span>
        </div>
        {!items.length ? (
          <div className="empty-state">
            <Database size={25}/>
            <strong>{busy ? 'Synchronizing memory...' : 'No memory records found.'}</strong>
            <span>{scope === 'guild' && !accessibleGuilds.length
              ? 'No verified Discord servers are available for this account.'
              : 'Create a record or change the search query to view stored memories.'}</span>
          </div>
        ) : (
          <div className="memory-record-list">
            {items.map(item => (
              <article className="memory-record" key={`${scope}-${item.id}`}>
                <div className="memory-record-main">
                  <div className="memory-record-meta">
                    <span>RECORD #{item.id}</span>
                    {item.category && <span className="memory-category">{item.category}</span>}
                    <span>{MEMORY_SOURCE_LABELS[item.source] || 'Unknown origin'}</span>
                    {item.revision > 0 && <span>REVISION {item.revision}</span>}
                  </div>
                  <p>{item.content}</p>
                  <small>{showArchived ? `ARCHIVED ${item.archived_at}` : `UPDATED ${item.updated_at || item.created_at || 'UNKNOWN'}`}</small>
                </div>
                {canManage && (
                  <div className="memory-record-actions">
                    {showArchived ? (
                      <button title="Restore memory" onClick={() => changeArchive(item)} disabled={busy}><ArchiveRestore size={14}/></button>
                    ) : (
                      <>
                        <button title="Edit memory" onClick={() => startEdit(item)} disabled={busy}><Pencil size={14}/></button>
                        <button title="Archive memory" onClick={() => changeArchive(item)} disabled={busy}><Archive size={14}/></button>
                        <button title="Delete memory" onClick={() => deleteMemory(item)} disabled={busy}><Trash2 size={14}/></button>
                      </>
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="footer-note">
        <span>ABUD MEMORY MATRIX / {scope.toUpperCase()}</span>
        <span>AUTHORIZATION: EXPLICIT SCOPE PERMISSION</span>
      </div>
    </div>
  );
}


function SecurityProtocol({ user }) {
  const [data, setData] = useState(null);
  const [scopeKey, setScopeKey] = useState('');
  const [identityId, setIdentityId] = useState('');
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function loadData(showLoading = true) {
    if (showLoading) setLoading(true);
    setError('');

    try {
      const result = await api('/auth/admin/identities');
      setData(result);

      const scopes = result.managed_scopes || [];
      const currentScope = scopes.find(
        s => `${s.scope_type}:${s.scope_id}` === scopeKey
      );
      const nextScope = currentScope
        ? scopeKey
        : scopes.length
          ? `${scopes[0].scope_type}:${scopes[0].scope_id}`
          : '';

      setScopeKey(nextScope);

      const candidates = (result.identities || []).filter(
        item => !item.is_creator && item.identity_id !== user.identity_id
      );
      const currentIdentity = candidates.find(
        item => item.identity_id === identityId
      );

      if (!currentIdentity && candidates.length) {
        setIdentityId(candidates[0].identity_id);
      } else if (!candidates.length) {
        setIdentityId('');
      }
    } catch (e) {
      setError(e.message || 'Gagal memuat daftar otorisasi.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData(true);
  }, []);

  const scopes = data?.managed_scopes || [];
  const selectedScope = scopes.find(
    s => `${s.scope_type}:${s.scope_id}` === scopeKey
  );

  const identities = (data?.identities || []).filter(
    item => !item.is_creator &&
      item.identity_id !== user.identity_id &&
      `${item.display_name || ''} ${item.identity_id} ${
        (item.accounts || []).map(a => a.provider).join(' ')
      }`.toLowerCase().includes(search.toLowerCase())
  );

  const selectedIdentity = identities.find(
    item => item.identity_id === identityId
  );

  const currentGrants = selectedIdentity?.permissions || [];
  const grantsForScope = currentGrants.filter(
    p => p.scope_type === selectedScope?.scope_type &&
      String(p.scope_id) === String(selectedScope?.scope_id)
  );

  const activePermissions = grantsForScope.map(p => p.permission);

  const manageablePermissions = selectedScope
    ? (data?.permissions_catalog || []).filter(permission =>
        user.is_creator || permissionHas(
          user,
          permission,
          selectedScope.scope_type,
          selectedScope.scope_id
        )
      )
    : [];

  useEffect(() => {
    setDraft(activePermissions);
  }, [identityId, scopeKey, data]);

  function togglePermission(permission, checked) {
    setDraft(previous => checked
      ? [...new Set([...previous, permission])]
      : previous.filter(item => item !== permission)
    );
  }

  async function savePermissions() {
    if (!selectedIdentity || !selectedScope || saving) return;

    setSaving(true);
    setError('');
    setNotice('');

    const toGrant = draft.filter(p =>
      !activePermissions.includes(p) && manageablePermissions.includes(p)
    );
    const toRevoke = activePermissions.filter(p =>
      !draft.includes(p) && manageablePermissions.includes(p)
    );

    const basePayload = {
      identity_id: selectedIdentity.identity_id,
      scope_type: selectedScope.scope_type,
      scope_id: selectedScope.scope_id
    };

    try {
      for (const permission of toGrant) {
        await api('/auth/admin/permissions/grant', {
          method: 'POST',
          body: JSON.stringify({ ...basePayload, permission })
        });
      }

      for (const permission of toRevoke) {
        await api('/auth/admin/permissions/revoke', {
          method: 'POST',
          body: JSON.stringify({ ...basePayload, permission })
        });
      }

      setNotice(
        `Authorization updated. ${toGrant.length} granted, ${toRevoke.length} revoked.`
      );
      await loadData(false);
    } catch (e) {
      setError(
        `${e.message || 'Authorization update failed.'} Refreshing current permissions.`
      );
      await loadData(false);
    } finally {
      setSaving(false);
    }
  }

  const providerLabel = account => {
    if (account.provider === 'discord') return 'DISCORD';
    if (account.provider === 'google') return 'GOOGLE';
    return String(account.provider || 'ACCOUNT').toUpperCase();
  };

  return (
    <div className="page-content security-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">INFRASTRUCTURE / ACCESS CONTROL</div>
          <h1>SECURITY <span>PROTOCOL.</span></h1>
          <p>Identity authorization, scoped permissions and delegated administration.</p>
        </div>
        <button className="outline-button" onClick={() => loadData(true)} disabled={loading || saving}>
          <RefreshCw size={14}/> REFRESH
        </button>
      </div>

      <div className="security-banner">
        <div className="security-banner-icon"><ShieldCheck size={22}/></div>
        <div>
          <strong>{user.is_creator ? 'CREATOR AUTHORITY' : 'DELEGATED AUTHORITY'}</strong>
          <span>
            {user.is_creator
              ? 'Full authorization control. Creator identity is protected from modification.'
              : 'Permission changes are restricted to your own delegated scopes and permissions.'}
          </span>
        </div>
        <span className="security-lock"><LockKeyhole size={14}/> BACKEND ENFORCED</span>
      </div>

      {error && <div className="memory-message memory-error"><AlertTriangle size={14}/>{error}</div>}
      {notice && <div className="memory-message memory-success"><ShieldCheck size={14}/>{notice}</div>}

      {loading ? (
        <div className="empty-state"><RefreshCw size={22}/><strong>Loading authorization registry...</strong></div>
      ) : !scopes.length ? (
        <div className="empty-state">
          <Shield size={25}/>
          <strong>No manageable scope</strong>
          <span>You need an explicit permissions.delegate grant to manage authorization.</span>
        </div>
      ) : (
        <>
          <section className="data-panel security-panel">
            <div className="panel-title">
              <span><Globe2 size={15}/> AUTHORIZATION SCOPE</span>
              <span className="panel-count">{scopes.length} MANAGED</span>
            </div>
            <label className="memory-field">
              <span>SELECT GLOBAL OR DISCORD SERVER</span>
              <select value={scopeKey} onChange={e => {
                setScopeKey(e.target.value);
                setNotice('');
              }}>
                {scopes.map(scope => {
                  const key = `${scope.scope_type}:${scope.scope_id}`;
                  return <option key={key} value={key}>
                    {scope.scope_type === 'global' ? 'GLOBAL' : 'GUILD'} // {scope.label}
                  </option>;
                })}
              </select>
            </label>
          </section>

          <section className="data-panel security-panel">
            <div className="panel-title">
              <span><Users size={15}/> TARGET IDENTITY</span>
              <span className="panel-count">{identities.length} AVAILABLE</span>
            </div>
            <div className="security-identity-tools">
              <label className="memory-search">
                <Search size={15}/>
                <input value={search} onChange={e => setSearch(e.target.value)}
                  placeholder="Search identity or provider..."/>
              </label>
              <select value={identityId} onChange={e => {
                setIdentityId(e.target.value);
                setNotice('');
              }}>
                {identities.map(item => (
                  <option key={item.identity_id} value={item.identity_id}>
                    {item.display_name || 'Unnamed identity'} // {item.accounts?.map(providerLabel).join(' + ') || 'NO PROVIDER'}
                  </option>
                ))}
              </select>
            </div>
            {selectedIdentity && (
              <div className="security-target">
                <div className="security-target-avatar">
                  {(selectedIdentity.display_name || 'A').slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <strong>{selectedIdentity.display_name || 'Unnamed identity'}</strong>
                  <small>
                    {selectedIdentity.accounts?.map(providerLabel).join(' / ') || 'No linked provider'}
                    {' '} · ID {selectedIdentity.identity_id}
                  </small>
                </div>
                <span className="security-target-status">ELIGIBLE</span>
              </div>
            )}
            {!identities.length && (
              <div className="security-empty">No eligible target identities. Your own identity and creator identity are excluded.</div>
            )}
          </section>

          <section className="data-panel security-panel">
            <div className="panel-title">
              <span><LockKeyhole size={15}/> PERMISSION MATRIX</span>
              <span className="panel-count">{draft.length} SELECTED</span>
            </div>
            {!selectedIdentity || !selectedScope ? (
              <div className="security-empty">Select a target identity and scope.</div>
            ) : !manageablePermissions.length ? (
              <div className="security-empty">
                You do not hold delegable permissions in this scope.
              </div>
            ) : (
              <div className="security-permission-grid">
                {manageablePermissions.map(permission => {
                  const checked = draft.includes(permission);
                  const alreadyGranted = activePermissions.includes(permission);
                  return (
                    <label className={`security-permission ${checked ? 'is-checked' : ''}`} key={permission}>
                      <input type="checkbox" checked={checked}
                        disabled={saving}
                        onChange={e => togglePermission(permission, e.target.checked)}/>
                      <span className="security-check"><ShieldCheck size={14}/></span>
                      <span className="security-permission-copy">
                        <strong>{permission}</strong>
                        <small>{alreadyGranted ? 'CURRENTLY GRANTED' : 'NOT GRANTED'}</small>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
            <div className="security-scope-note">
              <Shield size={14}/>
              Changes apply only to {selectedScope?.label || 'the selected scope'}.
              Backend revalidates every grant and revoke.
            </div>
            <div className="memory-editor-actions">
              <button className="memory-primary-button"
                onClick={savePermissions}
                disabled={saving || loading || !selectedIdentity || !manageablePermissions.length ||
                  (draft.filter(p => !activePermissions.includes(p)).length === 0 &&
                   activePermissions.filter(p => !draft.includes(p)).length === 0)}>
                <Save size={14}/> {saving ? 'APPLYING...' : 'SAVE AUTHORIZATION'}
              </button>
            </div>
          </section>
        </>
      )}

      <div className="footer-note">
        <span>ABUD SECURITY PROTOCOL</span>
        <span>CREATOR AUTHORITY IS IMMUTABLE</span>
      </div>
    </div>
  );
}


const improvementHints = {
  accuracy: ['Accuracy', 'Distinguish supported facts from assumptions. Say what is uncertain.'],
  missing_context: ['Missing context', 'State the relevant assumptions and address each constraint in the request.'],
  instructions: ['Did not follow instructions', 'Check that the answer follows the user’s requested format and constraints.'],
  clarity: ['Clarity', 'Lead with the answer and use short, concrete explanations.'],
};

function ImprovementPanel() {
  const [categories, setCategories] = useState([]);
  const [question, setQuestion] = useState('');
  const [candidate, setCandidate] = useState('');
  const [expected, setExpected] = useState('');
  const [result, setResult] = useState(null);
  const [feedbackError, setFeedbackError] = useState('');
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let active = true;
    api('/dashboard/improvement')
      .then((data) => { if (active) setCategories(data.categories); })
      .catch((e) => { if (active) setFeedbackError(e.message); });
    return () => { active = false; };
  }, []);

  async function evaluate(event) {
    event.preventDefault();
    if (running) return;
    setRunning(true);
    setError('');
    setResult(null);
    try {
      setResult(await api('/dashboard/improvement', {
        method: 'POST',
        body: JSON.stringify({
          question, candidate_instruction: candidate, expected_text: expected,
        }),
      }));
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="data-panel security-panel" aria-label="ABUD Improvement">
      <h2>ABUD Improvement</h2>
      <p>Voluntary issue counts and a side-by-side test of a proposed Web Chat instruction.</p>
      {feedbackError && <p role="alert">{feedbackError}</p>}
      {categories.length > 0 && <ul>
        {categories.map(({ category, count }) => (
          <li key={category}>
            {improvementHints[category]?.[0] || category}: {count}
            {improvementHints[category] && <button type="button" className="outline-button"
              disabled={running} onClick={() => setCandidate(improvementHints[category][1])}>
              Use suggested instruction
            </button>}
          </li>
        ))}
      </ul>}
      <form onSubmit={evaluate}>
        <fieldset disabled={running}>
          <legend>Compare baseline and candidate</legend>
          <p>Use a synthetic question. Each run sends two requests to the active 9Router model.</p>
          <label>Test question <textarea required maxLength={1500} value={question}
            onChange={(event) => setQuestion(event.target.value)} /></label>
          <label>Candidate instruction <textarea required maxLength={1200} value={candidate}
            onChange={(event) => setCandidate(event.target.value)} /></label>
          <label>Expected phrase <input required maxLength={240} value={expected}
            onChange={(event) => setExpected(event.target.value)} /></label>
          <button type="submit" className="outline-button"
            disabled={!question.trim() || !candidate.trim() || !expected.trim()}>
            {running ? 'Running comparison…' : 'Run comparison'}
          </button>
        </fieldset>
      </form>
      {error && <p role="alert">{error}</p>}
      {result && <div aria-live="polite">
        <p>{result.model} · {result.recommendation === 'review_candidate'
          ? 'Candidate met the phrase check. Review both answers before applying any change.'
          : result.recommendation === 'incomplete'
            ? 'Comparison incomplete. A truncated answer was not scored. Run the comparison again.'
            : 'This comparison needs more evidence.'}</p>
        <p>The phrase check measures text matching only.</p>
        {[['Baseline', result.baseline], ['Candidate', result.candidate]].map(([label, entry]) => (
          <div key={label}>
            <h3>{label} · {entry.truncated ? 'Truncated · Not scored' : entry.matched ? 'Phrase found' : 'Phrase missing'}</h3>
            <p style={{ whiteSpace: 'pre-wrap' }}>{entry.answer}</p>
          </div>
        ))}
      </div>}
    </section>
  );
}

function NeuralEngine({ user }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [inference, setInference] = useState(null);
  const [testingInference, setTestingInference] = useState(false);
  const [historyData, setHistoryData] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [analyticsPeriod, setAnalyticsPeriod] = useState('7d');

  async function load(initial = false) {
    if (initial) setLoading(true);
    else setRefreshing(true);
    setError('');

    try {
      const result = await api('/dashboard/neural-engine');
      setData(result);
    } catch (e) {
      setError(e.message || 'Gagal membaca status Neural Engine.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadHistory(showLoading = false, period = analyticsPeriod) {
    if (showLoading) setHistoryLoading(true);

    try {
      const result = await api(
        `/dashboard/neural-engine/history?limit=50&period=${encodeURIComponent(period)}`
      );
      setHistoryData(result);
    } catch (e) {
      console.error('Neural Engine history load failed:', e.message);
    } finally {
      if (showLoading) setHistoryLoading(false);
    }
  }

  async function testInference() {
    if (testingInference) return;

    setTestingInference(true);
    setInference(null);

    try {
      const result = await api(
        '/dashboard/neural-engine/test-inference',
        { method: 'POST' }
      );
      setInference(result);
    } catch (e) {
      setInference({
        success: false,
        error: e.message || 'Tes inference gagal dijalankan.',
        tested_at: new Date().toISOString(),
      });
    } finally {
      setTestingInference(false);
      await loadHistory(false);
    }
  }

  useEffect(() => {
    load(true);
    loadHistory(true);
  }, []);

  const online = data?.router_status === 'online';
  const statusLabel = loading
    ? 'CHECKING'
    : online ? 'ONLINE'
    : data?.router_status === 'degraded' ? 'DEGRADED'
    : 'OFFLINE';

  const inferenceStatus = testingInference
    ? 'RUNNING'
    : inference?.success
      ? 'SUCCESS'
      : inference
        ? 'FAILED'
        : 'NOT TESTED';

  return (
    <div className="page-content neural-page">
      <div className="page-heading neural-heading">
        <div>
          <div className="eyebrow">INTELLIGENCE / CORE MONITORING</div>
          <h1>NEURAL <span>ENGINE.</span></h1>
          <p>AI inference, model registry and router diagnostics.</p>
        </div>
        <div className="neural-actions">
          <button
            className="neural-test-button"
            onClick={testInference}
            disabled={testingInference || loading || !online}
          >
            <Activity size={14} className={testingInference ? 'neural-spin' : ''}/>
            {testingInference ? 'TESTING INFERENCE' : 'RUN INFERENCE TEST'}
          </button>
          <button
            className="neural-refresh"
            onClick={() => load(false)}
            disabled={loading || refreshing}
          >
            <RefreshCw size={14} className={refreshing ? 'neural-spin' : ''}/>
            {refreshing ? 'CHECKING' : 'REFRESH STATUS'}
          </button>
        </div>
      </div>

      {error && (
        <div className="neural-alert">
          <AlertTriangle size={15}/>
          <span>{error}</span>
        </div>
      )}

      {user.is_creator && <ImprovementPanel/>}

      <div className="neural-status-banner">
        <div className="neural-status-main">
          <div className={`neural-status-indicator ${online ? 'is-online' : data?.router_status === 'degraded' ? 'is-degraded' : ''}`}>
            <span/>
          </div>
          <div>
            <div className="eyebrow">9ROUTER CONNECTION</div>
            <strong>{statusLabel}</strong>
            <small>
              {data?.router_http_status
                ? `HTTP ${data.router_http_status}`
                : 'Awaiting router response'}
            </small>
          </div>
        </div>
        <div className="neural-readonly">
          <ShieldCheck size={15}/>
          CONFIGURATION LOCKED
        </div>
      </div>

      <div className="neural-metrics">
        <div className="neural-metric">
          <div className="neural-metric-icon"><Cpu size={18}/></div>
          <span>ACTIVE MODEL</span>
          <strong>{data?.active_model || '—'}</strong>
          <small>Loaded from server environment</small>
        </div>
        <div className="neural-metric">
          <div className="neural-metric-icon"><Network size={18}/></div>
          <span>ROUTING STRATEGY</span>
          <strong>{data?.routing_strategy || '—'}</strong>
          <small>Informational · Not editable</small>
        </div>
        <div className="neural-metric">
          <div className="neural-metric-icon"><Database size={18}/></div>
          <span>AVAILABLE MODELS</span>
          <strong>{data ? data.model_count : '—'}</strong>
          <small>Reported by router registry</small>
        </div>
        <div className="neural-metric">
          <div className="neural-metric-icon"><Activity size={18}/></div>
          <span>REGISTRY RESPONSE</span>
          <strong>{data?.latency_ms != null ? `${data.latency_ms} ms` : '—'}</strong>
          <small>Model registry request</small>
        </div>
      </div>

      <section className="neural-inference-panel">
        <div className="neural-panel-heading">
          <div>
            <div className="eyebrow">LIVE COMPLETION DIAGNOSTICS</div>
            <h2>INFERENCE <span>DIAGNOSTICS</span></h2>
          </div>
          <span className={`neural-inference-status ${inference?.success ? 'is-success' : inference && !testingInference ? 'is-failed' : ''}`}>
            <span/>
            {inferenceStatus}
          </span>
        </div>

        <div className="neural-inference-grid">
          <div className="neural-inference-item">
            <span>REQUESTED MODEL</span>
            <strong>{inference?.requested_model || data?.active_model || '—'}</strong>
          </div>
          <div className="neural-inference-item">
            <span>RESPONDING MODEL</span>
            <strong>{inference?.actual_model || '—'}</strong>
          </div>
          <div className="neural-inference-item">
            <span>INFERENCE LATENCY</span>
            <strong>{inference?.latency_ms != null ? `${inference.latency_ms} ms` : '—'}</strong>
          </div>
          <div className="neural-inference-item">
            <span>HTTP STATUS / TOKENS</span>
            <strong>
              {inference?.http_status
                ? `HTTP ${inference.http_status}${inference.total_tokens != null ? ` · ${inference.total_tokens} TOKENS` : ''}`
                : '—'}
            </strong>
          </div>
        </div>

        {inference?.success && (
          <div className="neural-inference-check">
            <span>PROMPT CHECK</span>
            <strong className={
              inference.response_check === 'EXACT_MATCH'
                ? 'is-exact'
                : inference.response_check === 'EXTRA_TEXT'
                  ? 'is-extra'
                  : 'is-mismatch'
            }>
              {{
                EXACT_MATCH: 'EXACT MATCH',
                EXTRA_TEXT: 'EXPECTED TEXT + EXTRA OUTPUT',
                MISMATCH: 'UNEXPECTED RESPONSE',
                NO_TEXT: 'NO DISPLAYABLE TEXT',
              }[inference.response_check] || 'NOT AVAILABLE'}
            </strong>
          </div>
        )}

        <div className={`neural-inference-response ${inference?.success ? 'is-success' : inference && !testingInference ? 'is-failed' : ''}`}>
          <span>MODEL RESPONSE</span>
          <p>
            {testingInference
              ? 'Sending a live completion request to 9Router...'
              : inference?.success
                ? inference.response
                : inference?.error
                  ? inference.error
                  : 'No inference test has been executed in this session.'}
          </p>
        </div>

        <div className="neural-inference-meta">
          <span>
            LAST INFERENCE TEST: {inference?.tested_at
              ? new Date(inference.tested_at).toLocaleString('id-ID')
              : 'NOT AVAILABLE'}
          </span>
          <small>This sends one live test request. It does not modify model or router configuration.</small>
        </div>
      </section>

      {data?.error && (
        <div className="neural-alert">
          <AlertTriangle size={15}/>
          <span>{data.error}</span>
        </div>
      )}

      <section className="neural-reliability">
        <div className="neural-panel-heading">
          <div>
            <div className="eyebrow">PERSISTENT DIAGNOSTICS</div>
            <h2>RELIABILITY <span>MONITOR</span></h2>
          </div>
          <div className="neural-analytics-actions">
            <select
              className="neural-period-select"
              value={analyticsPeriod}
              onChange={(event) => {
                const period = event.target.value;
                setAnalyticsPeriod(period);
                loadHistory(true, period);
              }}
              disabled={historyLoading}
              aria-label="Analytics period"
            >
              <option value="24h">LAST 24 HOURS</option>
              <option value="7d">LAST 7 DAYS</option>
              <option value="30d">LAST 30 DAYS</option>
              <option value="all">ALL TIME</option>
            </select>
            <button
              className="neural-refresh"
              onClick={() => loadHistory(true)}
              disabled={historyLoading}
            >
            <RefreshCw size={13} className={historyLoading ? 'neural-spin' : ''}/>
              {historyLoading ? 'LOADING' : 'REFRESH HISTORY'}
            </button>
          </div>
        </div>

        <div className="neural-reliability-metrics">
          {[
            ['TOTAL TESTS', historyData?.summary?.total_tests ?? 0],
            ['HTTP SUCCESS', `${historyData?.summary?.successful_requests ?? 0}`],
            ['FAILED REQUESTS', historyData?.summary?.failed_requests ?? 0],
            ['SUCCESS RATE', `${historyData?.summary?.success_rate ?? 0}%`],
            ['EXACT MATCH RATE', `${historyData?.summary?.exact_match_rate ?? 0}%`],
            ['ERROR RATE', `${historyData?.summary?.error_rate ?? 0}%`],
            ['AVG LATENCY', historyData?.summary?.average_latency_ms != null
              ? `${historyData.summary.average_latency_ms} ms` : '—'],
            ['P50 LATENCY', historyData?.summary?.p50_latency_ms != null
              ? `${historyData.summary.p50_latency_ms} ms` : '—'],
            ['P95 LATENCY', historyData?.summary?.p95_latency_ms != null
              ? `${historyData.summary.p95_latency_ms} ms` : '—'],
          ].map(([label, value]) => (
            <div className="neural-reliability-card" key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>

        <div className="neural-reliability-breakdown">
          <span>RESPONSE CHECKS</span>
          <div>
            <small>EXTRA TEXT <strong>{historyData?.summary?.extra_text ?? 0}</strong></small>
            <small>MISMATCH <strong>{historyData?.summary?.mismatches ?? 0}</strong></small>
            <small>NO TEXT <strong>{historyData?.summary?.no_text ?? 0}</strong></small>
          </div>
        </div>

        <div className="neural-history-section">
          <div className="neural-history-heading">
            <div>
              <div className="eyebrow">MODEL PERFORMANCE</div>
              <h3>PER-MODEL <span>STATISTICS</span></h3>
            </div>
          </div>

          {historyData?.models?.length ? (
            <div className="neural-table-wrap">
              <table className="neural-history-table">
                <thead>
                  <tr>
                    <th>MODEL</th>
                    <th>TESTS</th>
                    <th>SUCCESS</th>
                    <th>FAILED</th>
                    <th>EXACT</th>
                    <th>SUCCESS RATE</th>
                    <th>EXACT RATE</th>
                    <th>ERROR RATE</th>
                    <th>AVG LATENCY</th>
                    <th>P50</th>
                    <th>P95</th>
                  </tr>
                </thead>
                <tbody>
                  {historyData.models.map(model => (
                    <tr key={model.actual_model}>
                      <td>{model.actual_model}</td>
                      <td>{model.total_tests}</td>
                      <td>{model.successful_requests}</td>
                      <td>{model.failed_requests}</td>
                      <td>{model.exact_matches}</td>
                      <td>{model.success_rate}%</td>
                      <td>{model.exact_match_rate}%</td>
                      <td>{model.error_rate}%</td>
                      <td>{model.average_latency_ms != null
                        ? `${model.average_latency_ms} ms` : '—'}</td>
                      <td>{model.p50_latency_ms != null
                        ? `${model.p50_latency_ms} ms` : '—'}</td>
                      <td>{model.p95_latency_ms != null
                        ? `${model.p95_latency_ms} ms` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="neural-empty">
              {historyLoading ? 'LOADING MODEL STATISTICS...' : 'NO PERSISTED MODEL DATA YET'}
            </div>
          )}
        </div>

        <div className="neural-history-section">
          <div className="neural-history-heading">
            <div>
              <div className="eyebrow">LATEST 50 RECORDS · {analyticsPeriod.toUpperCase()}</div>
              <h3>INFERENCE <span>HISTORY</span></h3>
            </div>
            <span className="neural-count">
              {historyData?.history?.length ?? 0} RECORDS
            </span>
          </div>

          {historyData?.history?.length ? (
            <div className="neural-table-wrap">
              <table className="neural-history-table">
                <thead>
                  <tr>
                    <th>TIME</th>
                    <th>MODEL</th>
                    <th>STATUS</th>
                    <th>HTTP</th>
                    <th>LATENCY</th>
                    <th>PROMPT CHECK</th>
                  </tr>
                </thead>
                <tbody>
                  {historyData.history.map(item => (
                    <tr key={item.id}>
                      <td>{item.tested_at
                        ? new Date(item.tested_at).toLocaleString('id-ID')
                        : '—'}</td>
                      <td>{item.actual_model || item.requested_model}</td>
                      <td>
                        <span className={`neural-history-status ${item.request_status === 'success' ? 'is-success' : 'is-failed'}`}>
                          {item.request_status.toUpperCase()}
                        </span>
                      </td>
                      <td>{item.http_status ?? '—'}</td>
                      <td>{item.latency_ms != null ? `${item.latency_ms} ms` : '—'}</td>
                      <td>{item.response_check || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="neural-empty">
              {historyLoading ? 'LOADING INFERENCE HISTORY...' : 'NO INFERENCE HISTORY RECORDED'}
            </div>
          )}
        </div>

        <div className="neural-history-note">
          <ShieldCheck size={13}/>
          History stores diagnostic metadata only. Prompts, model response text, API keys and reasoning are not stored.
        </div>
      </section>

      <div className="neural-grid">
        <section className="neural-panel">
          <div className="neural-panel-heading">
            <div>
              <div className="eyebrow">MODEL REGISTRY</div>
              <h2>AVAILABLE <span>MODELS</span></h2>
            </div>
            <span className="neural-count">{data?.model_count ?? 0} DETECTED</span>
          </div>
          {loading && !data ? (
            <div className="neural-empty">READING MODEL REGISTRY...</div>
          ) : data?.models?.length ? (
            <div className="neural-model-list">
              {data.models.map((model, index) => (
                <div className="neural-model-row" key={model}>
                  <span className="neural-model-index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="neural-model-name">{model}</span>
                  {model === data.active_model && <span className="neural-active-tag">ACTIVE</span>}
                </div>
              ))}
            </div>
          ) : (
            <div className="neural-empty">MODEL REGISTRY UNAVAILABLE</div>
          )}
        </section>

        <section className="neural-panel">
          <div className="neural-panel-heading">
            <div>
              <div className="eyebrow">MODEL NAMESPACES</div>
              <h2>PROVIDER <span>INDEX</span></h2>
            </div>
            <Globe size={18}/>
          </div>
          {data?.providers?.length ? (
            <div className="neural-provider-list">
              {data.providers.map(provider => (
                <div className="neural-provider-row" key={provider.name}>
                  <div>
                    <strong>{provider.name}</strong>
                    <small>Models listed by router</small>
                  </div>
                  <span>{provider.model_count}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="neural-empty">NO PROVIDER NAMESPACES DETECTED</div>
          )}
          <div className="neural-info-note">
            <ShieldCheck size={14}/>
            Provider index is derived from model IDs. It does not represent individual provider uptime.
          </div>
        </section>
      </div>

      <div className="neural-footer">
        <span><LockKeyhole size={13}/> CONFIGURATION LOCKED TO SERVER</span>
        <span>
          LAST CHECK: {data?.checked_at
            ? new Date(data.checked_at).toLocaleString('id-ID')
            : 'NOT AVAILABLE'}
        </span>
      </div>
    </div>
  );
}


function ActivityLogs() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState('7d');
  const [action, setAction] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const pageSize = 25;

  async function load(options = {}) {
    const nextOffset = options.offset ?? offset;
    const nextPeriod = options.period ?? period;
    const nextAction = options.action ?? action;
    const nextSearch = options.search ?? search;

    if (nextOffset === 0 && !data) setLoading(true);
    else setRefreshing(true);

    setError('');

    const params = new URLSearchParams({
      period: nextPeriod,
      action: nextAction,
      q: nextSearch,
      limit: String(pageSize),
      offset: String(nextOffset),
    });

    try {
      const result = await api(`/dashboard/activity-logs?${params.toString()}`);
      setData(result);
      setOffset(nextOffset);
    } catch (e) {
      setError(e.message || 'Gagal membaca Activity Logs.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    load({ offset: 0 });
  }, []);

  function applyFilters(next = {}) {
    const nextPeriod = next.period ?? period;
    const nextAction = next.action ?? action;
    const nextSearch = next.search ?? search;

    setPeriod(nextPeriod);
    setAction(nextAction);
    setSearch(nextSearch);
    load({
      offset: 0,
      period: nextPeriod,
      action: nextAction,
      search: nextSearch,
    });
  }

  const history = data?.history || [];
  const total = data?.total || 0;
  const first = total ? offset + 1 : 0;
  const last = offset + history.length;

  return (
    <div className="page-content activity-page">
      <div className="page-heading activity-heading">
        <div>
          <div className="eyebrow">OPERATIONS / SECURITY AUDIT</div>
          <h1>ACTIVITY <span>LOGS.</span></h1>
          <p>Dashboard authentication, permission changes and memory audit events.</p>
        </div>
        <button
          className="neural-refresh"
          onClick={() => load()}
          disabled={loading || refreshing}
        >
          <RefreshCw size={14} className={refreshing ? 'neural-spin' : ''}/>
          {refreshing ? 'REFRESHING' : 'REFRESH LOGS'}
        </button>
      </div>

      <div className="activity-notice">
        <ShieldCheck size={15}/>
        READ ONLY AUDIT TRAIL · NO CREDENTIALS OR MEMORY CONTENT STORED
      </div>

      {error && (
        <div className="neural-alert">
          <AlertTriangle size={15}/>
          <span>{error}</span>
        </div>
      )}

      <div className="activity-summary">
        <div>
          <span>RECORDED EVENTS</span>
          <strong>{total.toLocaleString('id-ID')}</strong>
        </div>
        <div>
          <span>EVENT TYPES</span>
          <strong>{data?.actions?.length ?? 0}</strong>
        </div>
        <div>
          <span>ACTIVE FILTER</span>
          <strong>{period.toUpperCase()}</strong>
        </div>
      </div>

      <section className="activity-panel">
        <div className="activity-filter-bar">
          <label>
            <span>TIME RANGE</span>
            <select
              value={period}
              onChange={e => applyFilters({ period: e.target.value })}
            >
              <option value="24h">LAST 24 HOURS</option>
              <option value="7d">LAST 7 DAYS</option>
              <option value="30d">LAST 30 DAYS</option>
              <option value="all">ALL TIME</option>
            </select>
          </label>

          <label>
            <span>EVENT TYPE</span>
            <select
              value={action}
              onChange={e => applyFilters({ action: e.target.value })}
            >
              <option value="all">ALL EVENTS</option>
              {(data?.actions || []).map(item => (
                <option value={item.action} key={item.action}>
                  {item.action.toUpperCase()} ({item.count})
                </option>
              ))}
            </select>
          </label>

          <form
            className="activity-search"
            onSubmit={e => {
              e.preventDefault();
              applyFilters({ search: searchInput.trim() });
            }}
          >
            <span>SEARCH AUDIT TRAIL</span>
            <div>
              <input
                value={searchInput}
                onChange={e => setSearchInput(e.target.value)}
                placeholder="Actor, target, event or metadata..."
                maxLength={100}
              />
              <button type="submit" disabled={refreshing}>
                <Search size={14}/> SEARCH
              </button>
            </div>
          </form>
        </div>

        {search && (
          <div className="activity-search-state">
            SEARCH: <strong>{search}</strong>
            <button onClick={() => {
              setSearchInput('');
              applyFilters({ search: '' });
            }}>CLEAR</button>
          </div>
        )}

        <div className="activity-table-wrap">
          <table className="activity-table">
            <thead>
              <tr>
                <th>TIME</th>
                <th>ACTOR</th>
                <th>EVENT</th>
                <th>TARGET</th>
                <th>DETAILS</th>
              </tr>
            </thead>
            <tbody>
              {history.map(item => (
                <tr key={item.id}>
                  <td>
                    {item.created_at
                      ? new Date(item.created_at).toLocaleString('id-ID')
                      : '—'}
                  </td>
                  <td>{item.actor_display_name}</td>
                  <td>
                    <span className="activity-event">
                      {item.action}
                    </span>
                  </td>
                  <td>{item.target_display_name || '—'}</td>
                  <td className="activity-details">{item.details || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!history.length && (
            <div className="neural-empty">
              {loading ? 'LOADING AUDIT HISTORY...' : 'NO ACTIVITY FOUND FOR THIS FILTER'}
            </div>
          )}
        </div>

        <div className="activity-pagination">
          <span>
            SHOWING {first.toLocaleString('id-ID')}–{last.toLocaleString('id-ID')}
            {' '}OF {total.toLocaleString('id-ID')}
          </span>
          <div>
            <button
              onClick={() => load({ offset: Math.max(0, offset - pageSize) })}
              disabled={offset === 0 || refreshing}
            >
              PREVIOUS
            </button>
            <button
              onClick={() => load({ offset: offset + pageSize })}
              disabled={!data?.has_more || refreshing}
            >
              NEXT
            </button>
          </div>
        </div>
      </section>

      <div className="neural-history-note">
        <ShieldCheck size={13}/>
        Audit records are read-only. Existing audit history is retained; this page does not modify permissions or memory data.
      </div>
    </div>
  );
}


function NetworkCommand() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  async function load(initial = false) {
    if (initial) setLoading(true);
    else setRefreshing(true);

    setError('');

    try {
      const result = await api('/dashboard/network-command');
      setData(result);
    } catch (e) {
      setError(e.message || 'Gagal membaca status jaringan.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    load(true);
    const timer = setInterval(() => load(false), 30000);
    return () => clearInterval(timer);
  }, []);

  const services = data?.services || {};
  const overall = data?.overall_status || 'unknown';

  const statusLabel = (status) => {
    if (status === 'online') return 'ONLINE';
    if (status === 'degraded') return 'DEGRADED';
    if (status === 'offline') return 'OFFLINE';
    return 'UNKNOWN';
  };

  const cards = [
    {
      id: 'api',
      name: 'ABUD API',
      subtitle: 'DASHBOARD BACKEND',
      icon: Server,
      service: services.api,
      metric: 'ACTIVE',
      detail: services.api?.detail || 'API endpoint',
    },
    {
      id: 'bot',
      name: 'DISCORD GATEWAY',
      subtitle: 'ABUD BOT CONNECTION',
      icon: Bot,
      service: services.bot,
      metric: services.bot?.discord_latency_ms != null
        ? `${services.bot.discord_latency_ms} ms`
        : '—',
      detail: services.bot?.ready
        ? `${services.bot.guild_count} Discord servers`
        : 'Gateway not ready',
    },
    {
      id: 'router',
      name: '9ROUTER',
      subtitle: 'MODEL ROUTING CONNECTION',
      icon: Network,
      service: services.router,
      metric: services.router?.latency_ms != null
        ? `${services.router.latency_ms} ms`
        : '—',
      detail: services.router
        ? `${services.router.model_count} models detected`
        : 'Waiting for router',
    },
  ];

  return (
    <div className="page-content network-page">
      <div className="page-heading network-heading">
        <div>
          <div className="eyebrow">INFRASTRUCTURE / LIVE MONITORING</div>
          <h1>NETWORK <span>COMMAND.</span></h1>
          <p>Service connectivity, Discord gateway and routing diagnostics.</p>
        </div>
        <button
          className="neural-refresh"
          onClick={() => load(false)}
          disabled={loading || refreshing}
        >
          <RefreshCw size={14} className={refreshing ? 'neural-spin' : ''}/>
          {refreshing ? 'CHECKING' : 'REFRESH STATUS'}
        </button>
      </div>

      {error && (
        <div className="neural-alert">
          <AlertTriangle size={15}/>
          <span>{error}</span>
        </div>
      )}

      <div className="network-overview">
        <div className={`network-overview-dot status-${overall}`}/>
        <div className="network-overview-copy">
          <div className="eyebrow">INFRASTRUCTURE STATUS</div>
          <strong>{loading && !data ? 'CHECKING' : statusLabel(overall)}</strong>
          <small>
            {overall === 'online'
              ? 'All monitored services are responding.'
              : overall === 'degraded'
              ? 'One or more services need attention.'
              : overall === 'offline'
              ? 'One or more service connections are offline.'
              : 'Waiting for monitoring data.'}
          </small>
        </div>
        <div className="network-readonly">
          <ShieldCheck size={15}/>
          READ ONLY
        </div>
      </div>

      <div className="network-service-grid">
        {cards.map(card => {
          const Icon = card.icon;
          const status = card.service?.status || 'unknown';

          return (
            <section className="network-service-card" key={card.id}>
              <div className="network-card-top">
                <div className="network-card-icon"><Icon size={19}/></div>
                <span className={`network-status status-${status}`}>
                  <i/>
                  {statusLabel(status)}
                </span>
              </div>
              <div className="eyebrow">{card.subtitle}</div>
              <h2>{card.name}</h2>
              <strong className="network-card-metric">{card.metric}</strong>
              <small className="network-card-detail">{card.detail}</small>
              {card.service?.http_status && (
                <small className="network-http">
                  HTTP {card.service.http_status}
                </small>
              )}
              {card.service?.error && (
                <div className="network-card-error">
                  {card.service.error}
                </div>
              )}
            </section>
          );
        })}
      </div>

      <section className="network-panel">
        <div className="network-panel-heading">
          <div>
            <div className="eyebrow">INTERNAL ROUTING</div>
            <h2>CONNECTION <span>PATHS</span></h2>
          </div>
          <Wifi size={18}/>
        </div>

        <div className="network-connection-list">
          {(data?.connections || []).map((connection, index) => (
            <div className="network-connection-row" key={connection.name}>
              <div className="network-connection-number">
                {String(index + 1).padStart(2, '0')}
              </div>
              <div className="network-connection-name">
                {connection.name}
              </div>
              <span className={`network-status status-${connection.status}`}>
                <i/>
                {statusLabel(connection.status)}
              </span>
            </div>
          ))}
          {!data?.connections?.length && (
            <div className="neural-empty">WAITING FOR CONNECTION DATA...</div>
          )}
        </div>
      </section>

      <div className="neural-footer">
        <span><LockKeyhole size={13}/> SERVER CONFIGURATION IS LOCKED</span>
        <span>
          AUTO REFRESH: 30 SECONDS
          {' · '}
          LAST CHECK: {data?.checked_at
            ? new Date(data.checked_at).toLocaleString('id-ID')
            : 'NOT AVAILABLE'}
        </span>
      </div>
    </div>
  );
}


function ModulePlaceholder({ module }) {
  const Icon = module.icon;
  return (
    <div className="page-content">
      <div className="page-heading"><div><div className="eyebrow">{module.group} / MODULE</div><h1>{module.label.split(' ')[0]} <span>{module.label.split(' ').slice(1).join(' ')}.</span></h1><p>ABUD Tactical Intelligence System.</p></div></div>
      <div className="placeholder-panel">
        <div className="placeholder-icon"><Icon size={32}/></div>
        <div className="eyebrow">MODULE INITIALIZATION</div>
        <h2>Subsystem <span>not connected.</span></h2>
        <p>This module's interface is reserved. Backend endpoints and permission checks must be implemented before enabling its controls.</p>
        <div className="placeholder-status"><span className="pulse-dot"/> AWAITING BACKEND INTEGRATION</div>
      </div>
    </div>
  );
}

function Integrations() {
  const path = '/web/chat/integrations/canva';
  const [canva, setCanva] = useState(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState('');
  const [editor, setEditor] = useState('');
  const [error, setError] = useState('');
  const [notice] = useState(() => {
    const result = new URLSearchParams(window.location.search).get('canva');
    if (result === 'connected') return 'Akun Canva terhubung.';
    if (result === 'failed') return 'Canva belum terhubung. Coba lagi.';
    return '';
  });

  useEffect(() => {
    api(path).then(setCanva).catch(err => setError(err.message));
    const url = new URL(window.location.href);
    if (url.searchParams.has('canva')) {
      url.searchParams.delete('canva');
      window.history.replaceState(window.history.state, '', url);
    }
  }, []);

  async function change(action) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      if (action === 'connect') {
        const result = await api(path + '/connect', { method: 'POST' });
        window.location.assign(result.url);
      } else if (action === 'disconnect') {
        const result = await api(path, { method: 'DELETE' });
        setCanva(previous => ({ ...previous, ...result }));
        setEditor('');
      } else {
        setEditor('');
        const result = await api(path + '/designs', {
          method: 'POST', body: JSON.stringify({ title: title.trim() }),
        });
        setEditor(result.url);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="page-content">
    <div className="page-heading"><div><h1>Integrasi</h1><p>Hubungkan layanan untuk akun Abud lo.</p></div></div>
    <section className="placeholder-panel" aria-labelledby="canva-heading">
      <h2 id="canva-heading">Canva</h2>
      <p>Buat desain kosong untuk konten lo, lalu lanjutkan di editor Canva.</p>
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
      {canva && !canva.available && <p>Integrasi Canva belum tersedia.</p>}
      {canva?.available && <button type="button" disabled={busy} onClick={() => change('connect')}>
        {canva.connected ? 'Hubungkan ulang Canva' : 'Hubungkan Canva'}
      </button>}
      {canva?.connected && <button type="button" disabled={busy} onClick={() => change('disconnect')}>Putuskan koneksi</button>}
      {canva?.available && canva.connected && <form onSubmit={event => { event.preventDefault(); change('create'); }}>
        <label htmlFor="canva-title">Judul desain</label>
        <input id="canva-title" value={title} onChange={event => setTitle(event.target.value)} required maxLength={100} disabled={busy}/>
        <button disabled={busy || !title.trim()}>Buat desain 1080 × 1080</button>
      </form>}
      {editor && <a href={editor} target="_blank" rel="noopener noreferrer">Buka editor Canva</a>}
    </section>
    <section className="placeholder-panel" aria-labelledby="external-tools-heading">
      <h2 id="external-tools-heading">Layanan eksternal</h2>
      <p><a href="https://higgsfield.ai/" target="_blank" rel="noopener noreferrer">Buka Higgsfield</a></p>
      <p><a href="https://claude.ai/" target="_blank" rel="noopener noreferrer">Buka Claude</a></p>
    </section>
  </section>;
}

function App() {
  const [user, setUser] = useState(null);
  const [guilds, setGuilds] = useState([]);
  const [health, setHealth] = useState(null);
  const [active, setActive] = useState(() => new URLSearchParams(window.location.search).has('canva') ? 'integrations' : 'chat');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [mobileOpen, setMobileOpen] = useState(false);

  async function loadDashboard(initial = false) {
    if (!initial) setRefreshing(true);
    setError('');
    try {
      const [identity, status] = await Promise.all([
        api('/auth/me'),
        api('/health')
      ]);
      setUser(identity);
      setHealth(status);
      if (identity.dashboard_access) {
        const access = await api('/auth/guilds');
        setGuilds(access.guilds || []);
      } else {
        setGuilds([]);
      }
    } catch (e) {
      if (e.status === 401) setUser(null);
      else setError('Unable to verify services. Check API and Discord verification gateway.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => { loadDashboard(true); }, []);

  const visibleModules = modules.filter(module => canOpenModule(user, module.id));

  useEffect(() => {
    if (user && visibleModules.length && !visibleModules.some(m => m.id === active)) {
      setActive('chat');
    }
  }, [user, active, visibleModules.map(m => m.id).join('|')]);

  async function logout() {
    try {
      await api('/auth/logout', { method: 'POST' });
    } finally {
      window.location.href = '/';
    }
  }

  if (loading) return <div className="boot-screen"><CoreReactor status="INITIALIZING"/><span>ESTABLISHING SECURE CONNECTION</span></div>;
  if (!user) return <Login error={error}/>;
  if (!user.profile_completed) return <ProfileSetup/>;

  const current = visibleModules.find(m => m.id === active) || visibleModules[0];
  const groups = [...new Set(visibleModules.map(m => m.group))];

  return (
    <div className="app-shell">
      {mobileOpen && <button className="mobile-backdrop" onClick={() => setMobileOpen(false)} aria-label="Close menu"/>}
      <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-brand"><Brand/><button className="mobile-close" onClick={() => setMobileOpen(false)}><X size={18}/></button></div>
        <div className="system-chip"><span className="pulse-dot"/> SYSTEM OPERATIONAL <span className="chip-version">V1.0</span></div>
        <nav>
          {groups.map(group => <div className="nav-group" key={group}>
            <div className="nav-label">{group}</div>
            {visibleModules.filter(m => m.group === group).map(m => {
              const Icon = m.icon;
              return <button key={m.id} className={`nav-item ${active === m.id ? 'active' : ''}`} onClick={() => {setActive(m.id);setMobileOpen(false);}}>
                <Icon size={17}/><span>{m.label}</span>{active === m.id && <ChevronRight size={14} className="nav-arrow"/>}
              </button>;
            })}
          </div>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-user"><div className="user-avatar">{user.avatar_url ? <img src={user.avatar_url} alt="Profile"/> : (user.display_name || 'A').slice(0,1).toUpperCase()}</div><div className="user-label"><strong>{user.display_name || 'Operator'}</strong><small>{user.is_creator ? 'ROOT AUTHORITY' : 'AUTHORIZED USER'}</small></div><button onClick={logout} title="Sign out"><LogOut size={16}/></button></div>
          <div className="sidebar-version">ABUD CONTROL CENTER <span>BUILD 001</span></div>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left"><button className="mobile-menu" onClick={() => setMobileOpen(true)}><Menu size={19}/></button><span className="breadcrumb">ABUD <b>/</b> {current.label.toUpperCase()}</span></div>
          <div className="topbar-right"><span className="top-status"><i/> API {health?.status === 'healthy' ? 'CONNECTED' : 'UNKNOWN'}</span><span className="top-clock">UTC+7 / ID</span><div className="top-avatar">{user.avatar_url ? <img src={user.avatar_url} alt="Profile"/> : (user.display_name || 'A').slice(0,1).toUpperCase()}</div></div>
        </header>
        {error && <div className="global-error"><AlertTriangle size={15}/>{error}</div>}
        {active === 'chat' ? <React.Suspense fallback={<p>Loading AI Chat…</p>}><WebChat onOpenIntegrations={() => setActive('integrations')}/></React.Suspense> : active === 'integrations' ? <Integrations/> : active === 'overview' ? <Overview health={health} guilds={guilds} refresh={() => loadDashboard()} refreshing={refreshing} user={user}/> :
          active === 'memory' ? <MemoryMatrix user={user} guilds={guilds}/> :
          active === 'security' ? <SecurityProtocol user={user}/> :
          active === 'neural' ? <NeuralEngine user={user}/> :
          active === 'logs' ? <ActivityLogs/> :
          active === 'network' ? <NetworkCommand/> :
          <ModulePlaceholder module={current}/>}
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App/>);
