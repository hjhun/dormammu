export type TerminalSession = {
  id: string;
  cwd: string;
  command: string[];
  created_at: string;
  pid: number;
  running: boolean;
  exit_code: number | null;
  runtime?: string;
};

export type TelegramTurn = {
  role: string;
  kind: string;
  created_at: string;
  text: string;
};

export type TelegramSession = {
  id: string;
  path: string;
  updated_at: string | null;
  turn_count: number;
};

export type SettingsPayload = {
  scope: string;
  config_file: string | null;
  repo_root: string;
  active_agent_cli?: string | null;
  fallback_agent_clis: string[];
  token_exhaustion_patterns: string[];
  telegram: {
    bot_token?: string;
    allowed_chat_ids?: number[];
    stream_on_start?: boolean;
    chunk_size?: number;
    flush_interval_seconds?: number;
  };
  web: {
    allowed_roots: string[];
    host?: string;
    port?: number;
    password_configured?: boolean;
  };
  process_timeout_seconds?: number | null;
  fallback_on_nonzero_exit: boolean;
  resolved: Record<string, unknown>;
  raw_json: string;
};

export class ApiClient {
  constructor(private token: string) {}

  async authState(): Promise<{ password_configured: boolean; setup_required: boolean }> {
    const response = await fetch("/api/auth/state");
    return this.decode<{ password_configured: boolean; setup_required: boolean }>(response);
  }

  async setupPassword(password: string): Promise<{ ok: boolean }> {
    const response = await fetch("/api/auth/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password })
    });
    return this.decode<{ ok: boolean }>(response);
  }

  async login(): Promise<{ ok: boolean }> {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: this.token })
    });
    return this.decode<{ ok: boolean }>(response);
  }

  async get<T>(path: string): Promise<T> {
    const response = await fetch(path, { headers: this.headers() });
    return this.decode<T>(response);
  }

  async post<T>(path: string, body: unknown): Promise<T> {
    const response = await fetch(path, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body)
    });
    return this.decode<T>(response);
  }

  async patch<T>(path: string, body: unknown): Promise<T> {
    const response = await fetch(path, {
      method: "PATCH",
      headers: this.headers(),
      body: JSON.stringify(body)
    });
    return this.decode<T>(response);
  }

  async delete<T>(path: string): Promise<T> {
    const response = await fetch(path, { method: "DELETE", headers: this.headers() });
    return this.decode<T>(response);
  }

  wsUrl(path: string): string {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(path, `${protocol}//${window.location.host}`);
    if (this.token) url.searchParams.set("token", this.token);
    return url.toString();
  }

  private headers(): HeadersInit {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    return headers;
  }

  private async decode<T>(response: Response): Promise<T> {
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        detail = String(payload.detail || detail);
      } catch {
        // Keep status text.
      }
      throw new Error(detail);
    }
    return response.json() as Promise<T>;
  }
}
