import { useState } from "react";
import { clearSession, loadSession, login, logout, pick, saveSession } from "./api";
import { Activity } from "./Activity";
import { Studio } from "./Studio";

function groupLabels(groups) {
  if (!groups) return [];
  if (Array.isArray(groups)) return groups.map(String);
  if (typeof groups === "object") return Object.entries(groups).map(([id, name]) => name || id);
  return [String(groups)];
}

function sessionFromLogin(username, payload) {
  const token = pick(payload, "accessToken", "AccessToken");
  const user = pick(payload, "user", "User") || {};
  return {
    token,
    username: pick(user, "username", "Username") || username,
    displayName: pick(user, "displayName", "DisplayName") || username,
    email: pick(user, "email", "Email") || "",
    status: pick(user, "status", "Status") || "",
    roleProfile: pick(user, "roleProfile", "RoleProfile") || "",
    groups: pick(user, "groups", "Groups") || {},
    permissions: String(pick(payload, "permissions", "Permissions") || ""),
    identity: null,
  };
}

export function App() {
  const [session, setSession] = useState(() => loadSession());
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState("activity");

  async function onLogin(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = await login(username.trim(), password);
      const next = sessionFromLogin(username.trim(), payload);
      if (!next.token) throw new Error("Auth service did not return an access token.");
      saveSession(next);
      setPassword("");
      setSession(next);
    } catch (exc) {
      const down = exc.status === 500 || exc.status === 502 || exc.status === 503;
      setError(down ? "Auth service is unreachable. Start it, then try again." : exc.message || "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  async function onLogout() {
    const token = session?.token;
    clearSession();
    setSession(null);
    if (token) {
      try {
        await logout(token);
      } catch {
        /* The local session is already cleared. */
      }
    }
  }

  if (!session?.token) {
    return (
      <main className="login-screen">
        <form className="login-card" onSubmit={onLogin}>
          <p className="eyebrow">Platform studio</p>
          <h1>Sign in</h1>
          <p className="lede">
            Username and password go to the .NET auth service. That service checks them with Keycloak and returns the platform token this studio uses for every later call.
          </p>
          <label>
            Username
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          </label>
          {error ? <p className="error">{error}</p> : null}
          <button type="submit" disabled={busy}>{busy ? "Checking…" : "Continue"}</button>
        </form>
      </main>
    );
  }

  const identity = session.identity || {};
  const permissionCodes = Array.isArray(identity.permissions)
    ? identity.permissions.map(String)
    : String(session.permissions || "").split(",").map((item) => item.trim()).filter(Boolean);

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Agent studio</p>
          <strong>{session.displayName || session.username}</strong>
          <span className="muted"> {session.username}</span>
        </div>
        <nav className="page-nav">
          <button type="button" className={page === "activity" ? "selected" : "ghost"} onClick={() => setPage("activity")}>Activity</button>
          <button type="button" className={page === "test" ? "selected" : "ghost"} onClick={() => setPage("test")}>Test agent</button>
        </nav>
        <div className="session-facts">
          <span>{session.status || "Signed in"}</span>
          <span>{session.roleProfile || "No role profile"}</span>
          <span>{groupLabels(identity.groups || session.groups).join(", ") || "No groups"}</span>
          <span>Permissions {permissionCodes.join(", ") || "—"}</span>
        </div>
        <button type="button" className="ghost" onClick={onLogout}>Sign out</button>
      </header>
      {page === "activity" ? <Activity session={session} /> : <Studio session={session} />}
    </div>
  );
}
