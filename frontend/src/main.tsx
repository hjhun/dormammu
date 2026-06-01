import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import {
  Bot,
  ClipboardList,
  FileJson,
  FolderPlus,
  Gauge,
  Globe2,
  KeyRound,
  ListTodo,
  LogOut,
  MessageSquareText,
  Monitor,
  Play,
  PlugZap,
  Power,
  RefreshCw,
  Save,
  SendHorizontal,
  Settings,
  ShieldCheck,
  Square,
  TerminalSquare,
  Trash2
} from "lucide-react";
import { ApiClient, DaemonFile, DaemonStatus, SettingsPayload, TelegramSession, TelegramTurn, TerminalSession } from "./api";
import "./styles.css";

type View = "terminal" | "daemon" | "goals" | "telegram" | "settings";
type AuthState = "checking" | "setup" | "signed-out" | "signed-in";
type SettingsTab = "agent" | "telegram" | "web" | "advanced" | "raw";

function useCredential(): [string, (value: string) => void] {
  const [token, setTokenState] = useState(() => localStorage.getItem("dormammu.password") || "");
  const setToken = (value: string) => {
    if (value) {
      localStorage.setItem("dormammu.password", value);
      localStorage.removeItem("dormammu.token");
    } else {
      localStorage.removeItem("dormammu.password");
      localStorage.removeItem("dormammu.token");
    }
    setTokenState(value);
  };
  return [token, setToken];
}

function App() {
  const [token, setToken] = useCredential();
  const api = useMemo(() => new ApiClient(token), [token]);
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [view, setView] = useState<View>("terminal");
  const [status, setStatus] = useState("disconnected");
  const [repo, setRepo] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (authState !== "checking") return;
    let cancelled = false;
    api
      .authState()
      .then((state) => {
        if (cancelled) return;
        if (state.setup_required) {
          setToken("");
          setAuthState("setup");
          return;
        }
        if (!token) {
          setAuthState("signed-out");
          return;
        }
        return api.login().then(() => {
          if (!cancelled) setAuthState("signed-in");
        });
      })
      .catch(() => {
        if (!cancelled) {
          setToken("");
          setAuthState("signed-out");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, authState, setToken, token]);

  useEffect(() => {
    if (authState !== "signed-in") return;
    api
      .get<{ ok: boolean; repo_root: string }>("/api/health")
      .then((payload) => {
        setRepo(payload.repo_root);
        setStatus(payload.ok ? "online" : "degraded");
      })
      .catch((err: Error) => {
        setStatus("auth required");
        setError(err.message);
      });
  }, [api, authState]);

  const login = async (secret: string) => {
    const candidate = secret.trim();
    await new ApiClient(candidate).login();
    setToken(candidate);
    setAuthState("signed-in");
    setError("");
  };

  const setupPassword = async (password: string) => {
    await new ApiClient("").setupPassword(password);
    setToken(password);
    setAuthState("signed-in");
    setError("");
  };

  const logout = () => {
    setToken("");
    setAuthState("signed-out");
    setStatus("disconnected");
    setRepo("");
  };

  if (authState !== "signed-in") {
    return (
      <AuthScreen
        checking={authState === "checking"}
        mode={authState === "setup" ? "setup" : "login"}
        onLogin={login}
        onSetup={setupPassword}
      />
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">D</div>
          <div>
            <div className="brand-name">Dormammu</div>
            <div className="brand-subtitle">web terminal</div>
          </div>
        </div>
        <nav className="nav">
          <button className={view === "terminal" ? "active" : ""} onClick={() => setView("terminal")} title="Terminal sessions">
            <TerminalSquare size={18} /> Terminal
          </button>
          <button className={view === "daemon" ? "active" : ""} onClick={() => setView("daemon")} title="Daemon queue">
            <Gauge size={18} /> Queue
          </button>
          <button className={view === "goals" ? "active" : ""} onClick={() => setView("goals")} title="Daemon goals">
            <ListTodo size={18} /> Goals
          </button>
          <button className={view === "telegram" ? "active" : ""} onClick={() => setView("telegram")} title="Telegram sessions">
            <MessageSquareText size={18} /> Telegram
          </button>
          <button className={view === "settings" ? "active" : ""} onClick={() => setView("settings")} title="Settings">
            <Settings size={18} /> Settings
          </button>
        </nav>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">repo</div>
            <div className="repo-path">{repo || "waiting for server"}</div>
          </div>
          <div className="topbar-actions">
            <div className={`status ${status.replace(/\s+/g, "-")}`}>
              <PlugZap size={16} /> {status}
            </div>
            <button className="icon-button" onClick={logout} title="Log out"><LogOut size={16} /></button>
          </div>
        </header>
        {error && <div className="banner">{error}</div>}
        {view === "terminal" && <TerminalView api={api} />}
        {view === "daemon" && <DaemonView api={api} />}
        {view === "goals" && <GoalsView api={api} />}
        {view === "telegram" && <TelegramView api={api} />}
        {view === "settings" && <SettingsView api={api} />}
      </main>
    </div>
  );
}

function AuthScreen({
  checking,
  mode,
  onLogin,
  onSetup
}: {
  checking: boolean;
  mode: "login" | "setup";
  onLogin: (secret: string) => Promise<void>;
  onSetup: (password: string) => Promise<void>;
}) {
  const [secret, setSecret] = useState("");
  const [confirmSecret, setConfirmSecret] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const setup = mode === "setup";

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      if (setup) {
        if (secret.length < 8) throw new Error("Password must be at least 8 characters");
        if (secret !== confirmSecret) throw new Error("Passwords do not match");
        await onSetup(secret);
      } else {
        await onLogin(secret);
      }
    } catch (err) {
      setMessage((err as Error).message || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-panel" aria-busy={checking || busy}>
        <div className="brand login-brand">
          <div className="brand-mark">D</div>
          <div>
            <div className="brand-name">Dormammu</div>
            <div className="brand-subtitle">operator console</div>
          </div>
        </div>
        <form className="login-form" onSubmit={submit}>
          <label className="field">
            <span>{setup ? "New password" : "Server password"}</span>
            <input
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
              type="password"
              autoComplete={setup ? "new-password" : "current-password"}
              autoFocus
              disabled={checking || busy}
            />
          </label>
          {setup && (
            <label className="field">
              <span>Confirm password</span>
              <input
                value={confirmSecret}
                onChange={(event) => setConfirmSecret(event.target.value)}
                type="password"
                autoComplete="new-password"
                disabled={checking || busy}
              />
            </label>
          )}
          {message && <div className="inline-error">{message}</div>}
          <button className="login-button" disabled={checking || busy}>
            <KeyRound size={17} /> {checking || busy ? "Checking" : setup ? "Set password" : "Log in"}
          </button>
        </form>
      </section>
    </main>
  );
}

function DaemonView({ api }: { api: ApiClient }) {
  const [status, setStatus] = useState<DaemonStatus | null>(null);
  const [logs, setLogs] = useState<{ path: string | null; lines: string[] }>({ path: null, lines: [] });
  const [activePrompt, setActivePrompt] = useState<DaemonFile | null>(null);
  const [promptFilename, setPromptFilename] = useState("");
  const [promptContent, setPromptContent] = useState("");
  const [selectedQueue, setSelectedQueue] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    api.get<DaemonStatus>("/api/daemon/status")
      .then((payload) => {
        setStatus(payload);
        setSelectedQueue((items) => items.filter((item) => payload.queue.some((file) => file.filename === item)));
      })
      .catch((err: Error) => setMessage(err.message));
    api.get<{ path: string | null; lines: string[] }>("/api/daemon/logs")
      .then(setLogs)
      .catch(() => setLogs({ path: null, lines: [] }));
  };

  useEffect(() => {
    refresh();
  }, [api]);

  const action = async (kind: "start" | "stop") => {
    setBusy(true);
    setMessage("");
    try {
      const result = await api.post<{ started?: boolean; stopped?: boolean; pid?: number; message?: string }>(`/api/daemon/${kind}`, {});
      setMessage(result.message || `${kind} requested${result.pid ? `: pid ${result.pid}` : ""}`);
      refresh();
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const loadPrompt = async (file: DaemonFile) => {
    try {
      const payload = await api.get<DaemonFile>(`/api/daemon/prompts/${encodeURIComponent(file.filename)}`);
      setActivePrompt(payload);
      setPromptFilename(payload.filename);
      setPromptContent(payload.content || "");
      setMessage("");
    } catch (err) {
      setMessage((err as Error).message);
    }
  };

  const newPrompt = () => {
    setActivePrompt(null);
    setPromptFilename("");
    setPromptContent("");
    setMessage("");
  };

  const enqueue = async () => {
    if (!promptContent.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const payload = await api.post<{ queued: boolean; prompt: DaemonFile }>("/api/daemon/queue", { text: promptContent });
      await loadPrompt(payload.prompt);
      setMessage("Prompt queued");
      refresh();
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const savePrompt = async () => {
    const target = (activePrompt?.filename || "").trim();
    if (!target || !promptContent.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const payload = await api.put<{ saved: boolean; prompt: DaemonFile }>(
        `/api/daemon/prompts/${encodeURIComponent(target)}`,
        { content: promptContent }
      );
      await loadPrompt(payload.prompt);
      setMessage("Prompt saved");
      refresh();
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const toggleQueueSelection = (filename: string) => {
    setSelectedQueue((items) =>
      items.includes(filename) ? items.filter((item) => item !== filename) : [...items, filename]
    );
  };

  const deleteSelected = async () => {
    if (selectedQueue.length === 0) return;
    if (!window.confirm(`Delete ${selectedQueue.length} queued prompt(s)?`)) return;
    setBusy(true);
    setMessage("");
    try {
      await api.post<{ deleted: string[] }>("/api/daemon/queue/delete", { filenames: selectedQueue });
      if (activePrompt && selectedQueue.includes(activePrompt.filename)) newPrompt();
      setSelectedQueue([]);
      setMessage("Selected queued prompts deleted");
      refresh();
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="daemon-surface">
      <div className="daemon-header">
        <div>
          <h1>Daemon Queue</h1>
          <div className="settings-path">{status?.config_path || "daemonize.json"}</div>
        </div>
        <div className="daemon-actions">
          <button className="save-button" onClick={() => action("start")} disabled={busy}><Power size={16} /> Start</button>
          <button className="icon-text-button" onClick={() => action("stop")} disabled={busy}><Square size={15} /> Stop</button>
          <button className="icon-button" onClick={refresh} title="Refresh"><RefreshCw size={15} /></button>
        </div>
      </div>
      {message && <div className="banner">{message}</div>}
      <div className="daemon-grid">
        <div className="metric-strip">
          <div><span>Process</span><strong>{status?.pid_present ? "running" : "stopped"}</strong></div>
          <div><span>Heartbeat</span><strong>{status?.heartbeat_present ? "present" : "missing"}</strong></div>
          <div><span>Queue</span><strong>{status?.queue_depth ?? 0}</strong></div>
        </div>
        <div className="daemon-paths">
          <div><span>Prompts</span><code>{status?.prompt_path || ""}</code></div>
          <div><span>Results</span><code>{status?.result_path || ""}</code></div>
          <div><span>PID</span><code>{status?.pid_path || ""}</code></div>
        </div>
      </div>
      <div className="daemon-columns">
        <div className="daemon-panel">
          <div className="section-title">
            <ClipboardList size={17} /> Queue
            <button className="icon-button" onClick={newPrompt} title="New prompt"><FolderPlus size={15} /></button>
          </div>
          <div className="queue-toolbar">
            <button className="icon-text-button" onClick={deleteSelected} disabled={busy || selectedQueue.length === 0}>
              <Trash2 size={15} /> Delete selected
            </button>
            <span>{selectedQueue.length} selected</span>
          </div>
          <div className="file-list queue-list">
            {(status?.queue || []).map((file) => (
              <button key={file.filename} className={activePrompt?.filename === file.filename ? "selected" : ""} onClick={() => void loadPrompt(file)}>
                <input
                  type="checkbox"
                  checked={selectedQueue.includes(file.filename)}
                  onClick={(event) => event.stopPropagation()}
                  onChange={() => toggleQueueSelection(file.filename)}
                  aria-label={`Select ${file.filename}`}
                />
                <span>{file.filename}</span>
                <small>{Math.max(1, Math.ceil(file.size / 1024))} KiB</small>
              </button>
            ))}
          </div>
        </div>
        <div className="daemon-panel">
          <div className="section-title"><FileJson size={17} /> Prompt</div>
          <label className="field compact-field">
            <span>Filename</span>
            <input value={promptFilename} onChange={(event) => setPromptFilename(event.target.value)} placeholder="Created when enqueued" disabled />
          </label>
          <textarea className="daemon-prompt-editor" value={promptContent} onChange={(event) => setPromptContent(event.target.value)} placeholder="Write a daemon prompt, then enqueue it for daemonize..." />
          <div className="daemon-actions">
            {activePrompt ? (
              <button className="save-button" onClick={savePrompt} disabled={busy || !promptContent.trim()}><Save size={16} /> Save prompt</button>
            ) : (
              <button className="save-button" onClick={enqueue} disabled={busy || !promptContent.trim()}><SendHorizontal size={16} /> Enqueue prompt</button>
            )}
            <button className="icon-text-button" onClick={newPrompt}><FolderPlus size={16} /> New draft</button>
          </div>
        </div>
      </div>
      <div className="daemon-panel daemon-log-panel">
        <div className="section-title"><FileJson size={17} /> Logs</div>
          <div className="log-path">{logs.path || "No daemon logs yet"}</div>
          <pre className="log-output">{logs.lines.join("\n") || "No log output."}</pre>
      </div>
    </section>
  );
}

function GoalsView({ api }: { api: ApiClient }) {
  return <MarkdownFileManager api={api} title="Goals" endpoint="/api/daemon/goals" icon="goal" createMode="post" />;
}

function MarkdownFileManager({
  api,
  title,
  endpoint,
  createMode = "put"
}: {
  api: ApiClient;
  title: string;
  endpoint: string;
  icon: "prompt" | "goal";
  createMode?: "put" | "post";
}) {
  const [rootPath, setRootPath] = useState("");
  const [files, setFiles] = useState<DaemonFile[]>([]);
  const [active, setActive] = useState<DaemonFile | null>(null);
  const [filename, setFilename] = useState("");
  const [content, setContent] = useState("");
  const [message, setMessage] = useState("");

  const refresh = () =>
    api.get<{ path: string | null; prompts?: DaemonFile[]; goals?: DaemonFile[] }>(endpoint)
      .then((payload) => {
        const items = payload.prompts || payload.goals || [];
        setRootPath(payload.path || "");
        setFiles(items);
        if (!active && items[0]) void load(items[0]);
      })
      .catch((err: Error) => setMessage(err.message));

  useEffect(() => {
    refresh();
  }, [api, endpoint]);

  const load = async (file: DaemonFile) => {
    const payload = await api.get<DaemonFile>(`${endpoint}/${encodeURIComponent(file.filename)}`);
    setActive(payload);
    setFilename(payload.filename);
    setContent(payload.content || "");
    setMessage("");
  };

  const clearDraft = () => {
    setActive(null);
    setFilename("");
    setContent("");
    setMessage("");
  };

  const save = async () => {
    try {
      if (createMode === "post" && !active) {
        const payload = await api.post<{ saved: boolean; goal: DaemonFile }>(endpoint, { content });
        await load(payload.goal);
      } else {
        const target = (filename || active?.filename || "").trim();
        if (!target) throw new Error("Filename is required");
        const payload = await api.put<{ saved: boolean; prompt?: DaemonFile; goal?: DaemonFile }>(
          `${endpoint}/${encodeURIComponent(target)}`,
          { content }
        );
        await load((payload.prompt || payload.goal) as DaemonFile);
      }
      setMessage("Saved");
      refresh();
    } catch (err) {
      setMessage((err as Error).message);
    }
  };

  const remove = async () => {
    const target = active?.filename || filename;
    if (!target || !window.confirm(`Delete ${target}?`)) return;
    await api.delete(`${endpoint}/${encodeURIComponent(target)}`);
    clearDraft();
    refresh();
  };

  return (
    <section className="markdown-manager">
      <div className="daemon-header">
        <div>
          <h1>{title}</h1>
          <div className="settings-path">{rootPath || "Not configured"}</div>
        </div>
        <div className="daemon-actions">
          <button className="icon-text-button" onClick={clearDraft}><FolderPlus size={16} /> New</button>
          <button className="save-button" onClick={save} disabled={!content.trim()}><Save size={16} /> Save</button>
          <button className="icon-button" onClick={remove} title="Delete" disabled={!active && !filename}><Trash2 size={15} /></button>
          <button className="icon-button" onClick={refresh} title="Refresh"><RefreshCw size={15} /></button>
        </div>
      </div>
      {message && <div className="banner">{message}</div>}
      <div className="markdown-grid">
        <div className="file-list">
          {files.map((file) => (
            <button key={file.filename} className={active?.filename === file.filename ? "selected" : ""} onClick={() => void load(file)}>
              <span>{file.filename}</span>
              <small>{Math.max(1, Math.ceil(file.size / 1024))} KiB</small>
            </button>
          ))}
        </div>
        <div className="editor-pane">
          <label className="field">
            <span>Filename</span>
            <input value={filename} onChange={(event) => setFilename(event.target.value)} placeholder={createMode === "post" && !active ? "Generated from first line" : "001-task.md"} disabled={createMode === "post" && !active} />
          </label>
          <textarea className="markdown-editor" value={content} onChange={(event) => setContent(event.target.value)} placeholder={title === "Goals" ? "Describe a recurring daemon goal..." : "Write a daemon prompt..."} />
        </div>
      </div>
    </section>
  );
}

function TerminalView({ api }: { api: ApiClient }) {
  const [sessions, setSessions] = useState<TerminalSession[]>([]);
  const [allowedRoots, setAllowedRoots] = useState<string[]>([]);
  const [cwd, setCwd] = useState("");
  const [active, setActive] = useState<TerminalSession | null>(null);
  const [error, setError] = useState("");

  const refresh = () =>
    api
      .get<{ sessions: TerminalSession[]; allowed_roots: string[] }>("/api/terminal/sessions")
      .then((payload) => {
        setSessions(payload.sessions);
        setAllowedRoots(payload.allowed_roots);
        if (!cwd) setCwd(payload.allowed_roots[0] || "");
        if (!active && payload.sessions[0]) setActive(payload.sessions[0]);
      })
      .catch((err: Error) => setError(err.message));

  useEffect(() => {
    void refresh();
  }, [api]);

  const create = async () => {
    try {
      const payload = await api.post<{ session: TerminalSession }>("/api/terminal/sessions", { cwd, cols: 120, rows: 32 });
      setSessions((items) => [payload.session, ...items]);
      setActive(payload.session);
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (session: TerminalSession) => {
    if (!window.confirm(`Close terminal ${session.id}?`)) return;
    await api.delete(`/api/terminal/sessions/${session.id}`);
    setSessions((items) => items.filter((item) => item.id !== session.id));
    if (active?.id === session.id) setActive(null);
  };

  return (
    <section className="panel-grid">
      <div className="session-list">
        <div className="section-title">
          <Monitor size={17} /> Sessions
          <button className="icon-button" onClick={refresh} title="Refresh"><RefreshCw size={15} /></button>
        </div>
        <div className="cwd-row">
          <select value={cwd} onChange={(event) => setCwd(event.target.value)}>
            {allowedRoots.map((root) => <option key={root}>{root}</option>)}
          </select>
          <button className="primary-icon" onClick={create} title="New terminal"><FolderPlus size={17} /></button>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <div className="session-stack">
          {sessions.map((session) => (
            <button key={session.id} className={`session-row ${active?.id === session.id ? "selected" : ""}`} onClick={() => setActive(session)}>
              <span>{session.id}</span>
              <small>{session.source || session.runtime || "tmux"} · {session.running ? "running" : `exit ${session.exit_code ?? ""}`}</small>
              <Trash2 size={15} onClick={(event) => { event.stopPropagation(); void remove(session); }} />
            </button>
          ))}
        </div>
      </div>
      <div className="terminal-stage">
        {active ? <XtermPanel key={active.id} api={api} session={active} /> : <div className="empty-state">Create a terminal session to begin.</div>}
      </div>
    </section>
  );
}

function XtermPanel({ api, session }: { api: ApiClient; session: TerminalSession }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const [inputMode, setInputMode] = useState<"command" | "run" | "run-once" | "resume">("command");
  const [inputValue, setInputValue] = useState("");
  const [lastCommand, setLastCommand] = useState(session.last_command || "");
  const [socketState, setSocketState] = useState("connecting");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!ref.current) return;
    setSocketState("connecting");
    setError("");
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: '"JetBrains Mono", "SFMono-Regular", Consolas, monospace',
      fontSize: 13,
      theme: { background: "#0b0d10", foreground: "#d8e0e6", cursor: "#f5c542" }
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(ref.current);
    termRef.current = term;
    fit.fit();
    const socket = new WebSocket(api.wsUrl(`/api/terminal/sessions/${session.id}/ws`));
    socketRef.current = socket;
    socket.addEventListener("open", () => {
      setSocketState("connected");
      fit.fit();
      socket.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      term.focus();
    });
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "output") term.write(message.data);
      if (message.type === "snapshot") {
        term.clear();
        term.write(message.data.replace(/\n/g, "\r\n"));
      }
      if (message.type === "status") term.writeln(`\r\n[session exited: ${message.exit_code ?? "closed"}]`);
    });
    socket.addEventListener("close", () => setSocketState("closed"));
    socket.addEventListener("error", () => {
      setSocketState("error");
      setError("Terminal stream disconnected");
    });
    const disposable = term.onData((data) => socket.readyState === WebSocket.OPEN && socket.send(JSON.stringify({ type: "input", data })));
    const resize = () => {
      fit.fit();
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    };
    window.addEventListener("resize", resize);
    return () => {
      disposable.dispose();
      window.removeEventListener("resize", resize);
      socket.close();
      term.dispose();
      termRef.current = null;
      socketRef.current = null;
    };
  }, [api, session.id]);

  useEffect(() => {
    setLastCommand(session.last_command || "");
  }, [session.last_command]);

  const submitTerminalInput = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (inputMode !== "resume" && !inputValue.trim()) return;
    try {
      if (inputMode === "command") {
        await api.post<{ written: boolean }>(`/api/terminal/sessions/${session.id}/input`, { command: inputValue });
        setLastCommand(inputValue.trim());
      } else {
        const payload = inputMode === "resume"
          ? { mode: inputMode }
          : { mode: inputMode, prompt: inputValue };
        const result = await api.post<{ written: boolean; command: string }>(`/api/terminal/sessions/${session.id}/dormammu`, payload);
        setLastCommand(result.command);
      }
      setInputValue("");
      setError("");
      termRef.current?.focus();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const focusTerminal = () => termRef.current?.focus();

  return (
    <div className="terminal-console">
      <div className="terminal-strip">
        <span>{session.cwd}</span>
        <small>{lastCommand || socketState}</small>
      </div>
      <div className="xterm-host" ref={ref} onClick={focusTerminal} />
      <form className="terminal-input-bar" onSubmit={submitTerminalInput}>
        <select value={inputMode} onChange={(event) => setInputMode(event.target.value as "command" | "run" | "run-once" | "resume")}>
          <option value="command">command</option>
          <option value="run">run</option>
          <option value="run-once">run-once</option>
          <option value="resume">resume</option>
        </select>
        <input
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder={inputMode === "command" ? "Type a terminal command" : inputMode === "resume" ? "Resume latest state" : "Prompt"}
          autoComplete="off"
          spellCheck={false}
          disabled={inputMode === "resume"}
        />
        <button className="primary-icon" title={inputMode === "command" ? "Send command" : "Run Dormammu"} disabled={inputMode !== "resume" && !inputValue.trim()}>
          {inputMode === "command" ? <SendHorizontal size={17} /> : <Play size={17} />}
        </button>
      </form>
      {error && <div className="inline-error command-error">{error}</div>}
    </div>
  );
}

function TelegramView({ api }: { api: ApiClient }) {
  const [sessions, setSessions] = useState<TelegramSession[]>([]);
  const [active, setActive] = useState<TelegramSession | null>(null);
  const [turns, setTurns] = useState<TelegramTurn[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  const refresh = () =>
    api.get<{ sessions: TelegramSession[] }>("/api/telegram/sessions")
      .then((payload) => setSessions(payload.sessions))
      .catch((err: Error) => setError(err.message));

  useEffect(() => {
    void refresh();
  }, [api]);
  useEffect(() => {
    if (!active) return;
    api.get<{ turns: TelegramTurn[] }>(`/api/telegram/sessions/${active.id}`)
      .then((payload) => setTurns(payload.turns))
      .catch((err: Error) => setError(err.message));
  }, [api, active]);

  const send = async () => {
    if (!active || !text.trim()) return;
    const message = text;
    setText("");
    const payload = await api.post<{ session: { turns: TelegramTurn[] } }>(`/api/telegram/sessions/${active.id}/messages`, { text: message });
    setTurns(payload.session.turns);
  };

  return (
    <section className="panel-grid">
      <div className="session-list">
        <div className="section-title"><MessageSquareText size={17} /> Telegram <button className="icon-button" onClick={refresh} title="Refresh"><RefreshCw size={15} /></button></div>
        {error && <div className="inline-error">{error}</div>}
        <div className="session-stack">
          {sessions.map((session) => (
            <button key={session.id} className={`session-row ${active?.id === session.id ? "selected" : ""}`} onClick={() => setActive(session)}>
              <span>{session.id}</span>
              <small>{session.turn_count} turns</small>
            </button>
          ))}
        </div>
      </div>
      <div className="conversation">
        <div className="turns">
          {turns.map((turn, index) => (
            <div className={`turn ${turn.role}`} key={`${turn.created_at}-${index}`}>
              <strong>{turn.role}</strong>
              <p>{turn.text}</p>
            </div>
          ))}
        </div>
        <div className="composer">
          <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Continue this session from the browser..." />
          <button onClick={send}>Send</button>
        </div>
      </div>
    </section>
  );
}

function SettingsView({ api }: { api: ApiClient }) {
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [scope, setScope] = useState<"project" | "global">("global");
  const [activeTab, setActiveTab] = useState<SettingsTab>("agent");
  const [rawDraft, setRawDraft] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setSettings(null);
    setMessage("");
    api
      .get<SettingsPayload>(`/api/config?scope=${scope}`)
      .then((payload) => {
        setSettings(payload);
        setRawDraft(payload.raw_json || "{}\n");
      })
      .catch((err: Error) => setMessage(err.message));
  }, [api, scope]);

  if (!settings) return <div className="empty-state">Loading settings...</div>;

  const update = <K extends keyof SettingsPayload>(key: K, value: SettingsPayload[K]) => setSettings({ ...settings, [key]: value });
  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const payload = activeTab === "raw"
        ? await api.patch<{ settings: SettingsPayload }>("/api/config/raw", { raw_json: rawDraft, scope })
        : await api.patch<{ settings: SettingsPayload }>("/api/config", { ...settings, scope });
      setSettings(payload.settings);
      setRawDraft(payload.settings.raw_json || "{}\n");
      setMessage("Saved");
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const cliOptions = uniqueOptions([
    settings.active_agent_cli || "",
    ...settings.fallback_agent_clis,
    "codex",
    "claude",
    "gemini",
    "cline"
  ]);
  const hostOptions = uniqueOptions([settings.web.host || "", "0.0.0.0", "127.0.0.1", "localhost"]);
  const tabs = [
    { id: "agent" as SettingsTab, label: "Agent", detail: "CLI", icon: Bot },
    { id: "telegram" as SettingsTab, label: "Telegram", detail: "Bot", icon: MessageSquareText },
    { id: "web" as SettingsTab, label: "Web", detail: "Access", icon: Globe2 },
    { id: "advanced" as SettingsTab, label: "Advanced", detail: "Runtime", icon: Gauge },
    { id: "raw" as SettingsTab, label: "Raw JSON", detail: "Config", icon: FileJson }
  ];
  const ActiveIcon = tabs.find((tab) => tab.id === activeTab)?.icon || Settings;

  return (
    <section className="settings-surface">
      <div className="settings-header">
        <div>
          <h1>Settings</h1>
          <div className="settings-path">{settings.config_file || "~/.dormammu/config"}</div>
        </div>
        <div className="segmented">
          <button className={scope === "global" ? "active" : ""} onClick={() => setScope("global")}>Global</button>
          <button className={scope === "project" ? "active" : ""} onClick={() => setScope("project")}>Project</button>
        </div>
        <button className="save-button" onClick={save} disabled={saving}><Save size={16} /> Save</button>
      </div>
      {message && <div className="banner">{message}</div>}
      <div className="settings-layout">
        <nav className="settings-tabs">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button key={tab.id} className={activeTab === tab.id ? "active" : ""} onClick={() => setActiveTab(tab.id)}>
                <Icon size={17} />
                <span>{tab.label}</span>
                <small>{tab.detail}</small>
              </button>
            );
          })}
        </nav>
        <div className="settings-editor">
          <div className="settings-section-title">
            <ActiveIcon size={18} />
            <strong>{tabs.find((tab) => tab.id === activeTab)?.label}</strong>
          </div>

          {activeTab === "agent" && (
            <div className="settings-fields">
              <SelectField label="Active CLI" value={settings.active_agent_cli || ""} options={cliOptions} onChange={(value) => update("active_agent_cli", value)} />
              <ListField label="Fallback CLIs" values={settings.fallback_agent_clis || []} onChange={(values) => update("fallback_agent_clis", values)} />
              <ListField label="Token exhaustion patterns" values={settings.token_exhaustion_patterns || []} onChange={(values) => update("token_exhaustion_patterns", values)} />
            </div>
          )}

          {activeTab === "telegram" && (
            <div className="settings-fields">
              <Field label="Bot token" value={settings.telegram?.bot_token || ""} type="password" onChange={(value) => update("telegram", { ...settings.telegram, bot_token: value })} />
              <ListField label="Allowed chat IDs" values={(settings.telegram?.allowed_chat_ids || []).map(String)} onChange={(values) => update("telegram", { ...settings.telegram, allowed_chat_ids: values.filter(Boolean).map(Number) })} />
            </div>
          )}

          {activeTab === "web" && (
            <div className="settings-fields">
              <div className="status-line">
                <ShieldCheck size={16} />
                <span>{settings.web.password_configured ? "Password configured" : "Password not configured"}</span>
              </div>
              <ListField label="Allowed roots" values={settings.web.allowed_roots || []} onChange={(values) => update("web", { ...settings.web, allowed_roots: values })} />
              <SelectField label="Host" value={settings.web.host || ""} options={hostOptions} onChange={(value) => update("web", { ...settings.web, host: value })} />
              <Field label="Port" value={String(settings.web.port || "")} onChange={(value) => update("web", { ...settings.web, port: Number(value) || undefined })} />
            </div>
          )}

          {activeTab === "advanced" && (
            <div className="settings-fields">
              <Field label="Process timeout seconds" value={String(settings.process_timeout_seconds || "")} onChange={(value) => update("process_timeout_seconds", Number(value) || null)} />
              <label className="toggle-row">
                <input type="checkbox" checked={settings.fallback_on_nonzero_exit} onChange={(event) => update("fallback_on_nonzero_exit", event.target.checked)} />
                Fallback on nonzero exit
              </label>
            </div>
          )}

          {activeTab === "raw" && (
            <label className="field raw-field">
              <span>{settings.config_file}</span>
              <textarea value={rawDraft} onChange={(event) => setRawDraft(event.target.value)} spellCheck={false} />
            </label>
          )}
        </div>
      </div>
    </section>
  );
}

function uniqueOptions(values: string[]): string[] {
  return values.map((value) => value.trim()).filter((value, index, items) => value && items.indexOf(value) === index);
}

function Field({ label, value, type = "text", onChange }: { label: string; value: string; type?: string; onChange: (value: string) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value=""></option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function ListField({ label, values, onChange }: { label: string; values: string[]; onChange: (values: string[]) => void }) {
  return (
    <label className="field list-field">
      <span>{label}</span>
      <textarea value={values.join("\n")} onChange={(event) => onChange(event.target.value.split("\n"))} />
    </label>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
