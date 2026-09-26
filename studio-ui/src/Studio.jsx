import { useEffect, useMemo, useRef, useState } from "react";
import {
  agentIdOf,
  agentNameOf,
  createThread,
  listAgents,
  listRuns,
  listThreads,
  pick,
  startRun,
  uploadArtifact,
} from "./api";

function formatWhen(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function shortId(value) {
  const text = String(value || "");
  return text.length > 8 ? text.slice(0, 8) : text;
}

function groupLabels(groups) {
  if (!groups) return [];
  if (Array.isArray(groups)) return groups.map(String);
  if (typeof groups === "object") return Object.entries(groups).map(([id, name]) => name || id);
  return [String(groups)];
}

function stepLabel(step) {
  if (!step) return "";
  if (typeof step === "string") return step;
  return step.name || step.detail || JSON.stringify(step);
}

export function Studio({ session, onLogout }) {
  const [agents, setAgents] = useState([]);
  const [agentError, setAgentError] = useState("");
  const [manualAgentId, setManualAgentId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [threads, setThreads] = useState([]);
  const [threadId, setThreadId] = useState("");
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [message, setMessage] = useState("");
  const [file, setFile] = useState(null);
  const fileInput = useRef(null);
  const [attached, setAttached] = useState([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const token = session.token;
  const selectedRun = runs.find((run) => String(pick(run, "runId", "RunId")) === selectedRunId) || null;
  const identity = session.identity || {};
  const permissionCodes = useMemo(() => {
    const fromMe = identity.permissions || identity.Permissions;
    if (Array.isArray(fromMe)) return fromMe.map(String);
    return String(session.permissions || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }, [identity, session.permissions]);

  async function refreshAgents() {
    setAgentError("");
    try {
      const rows = await listAgents(token);
      setAgents(rows);
      if (!agentId && rows[0]) setAgentId(agentIdOf(rows[0]));
    } catch (exc) {
      setAgents([]);
      setAgentError(exc.message || "Could not list agents.");
    }
  }

  async function refreshThreads(nextAgentId = agentId) {
    if (!nextAgentId) {
      setThreads([]);
      return;
    }
    const rows = await listThreads(token, nextAgentId);
    const list = Array.isArray(rows) ? rows : [];
    setThreads(list);
    if (!list.some((thread) => String(pick(thread, "threadId")) === threadId)) {
      setThreadId(list[0] ? String(pick(list[0], "threadId")) : "");
    }
  }

  async function refreshRuns(nextThreadId = threadId) {
    if (!agentId || !nextThreadId) {
      setRuns([]);
      return;
    }
    const rows = await listRuns(token, agentId, nextThreadId);
    const list = Array.isArray(rows) ? rows : [];
    setRuns(list);
    if (list[0] && !list.some((run) => String(pick(run, "runId")) === selectedRunId)) {
      setSelectedRunId(String(pick(list[0], "runId")));
    }
  }

  useEffect(() => {
    refreshAgents();
  }, [token]);

  useEffect(() => {
    if (!agentId) return undefined;
    setError("");
    refreshThreads(agentId).catch((exc) => setError(exc.message));
    return undefined;
  }, [agentId, token]);

  useEffect(() => {
    if (!threadId) {
      setRuns([]);
      return undefined;
    }
    refreshRuns(threadId).catch((exc) => setError(exc.message));
    const timer = setInterval(() => {
      refreshRuns(threadId).catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [threadId, agentId, token]);

  async function onCreateThread(executionType) {
    setBusy("thread");
    setError("");
    try {
      const created = await createThread(token, agentId, executionType);
      const id = String(pick(created, "threadId"));
      setThreadId(id);
      setAttached([]);
      await refreshThreads(agentId);
      setThreadId(id);
      setNotice(`Opened ${executionType.toLowerCase()} thread ${shortId(id)}.`);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function onUpload() {
    if (!file || !threadId) return;
    setBusy("upload");
    setError("");
    try {
      const stored = await uploadArtifact(token, agentId, threadId, file);
      setAttached((current) => [...current, stored]);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setNotice(`Attached ${stored.filename}.`);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function onSend(event) {
    event.preventDefault();
    if (!message.trim() || !threadId) return;
    setBusy("run");
    setError("");
    try {
      const result = await startRun(
        token,
        agentId,
        threadId,
        message.trim(),
        attached.map((item) => item.artifactId),
      );
      setMessage("");
      setAttached([]);
      setNotice("Run finished.");
      await refreshRuns(threadId);
      const runId = pick(result, "runId", "RunId");
      if (runId) setSelectedRunId(String(runId));
    } catch (exc) {
      setError(exc.message);
      refreshRuns(threadId).catch(() => {});
    } finally {
      setBusy("");
    }
  }

  function useManualAgent(event) {
    event.preventDefault();
    const value = manualAgentId.trim();
    if (!value) return;
    setAgentId(value);
    setThreadId("");
    setAttached([]);
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Agent studio</p>
          <strong>{session.displayName || session.username}</strong>
          <span className="muted"> {session.username}</span>
        </div>
        <div className="session-facts">
          <span>{session.status || "Signed in"}</span>
          <span>{session.roleProfile || "No role profile"}</span>
          <span>{groupLabels(identity.groups || session.groups).join(", ") || "No groups"}</span>
          <span>Permissions {permissionCodes.join(", ") || "—"}</span>
        </div>
        <button type="button" className="ghost" onClick={onLogout}>Sign out</button>
      </header>

      <div className="workspace">
        <aside className="panel">
          <div className="panel-head">
            <h2>Agents</h2>
            <button type="button" className="ghost" onClick={refreshAgents}>Refresh</button>
          </div>
          {agentError ? <p className="error">{agentError}</p> : null}
          <ul className="stack-list">
            {agents.map((agent) => {
              const id = agentIdOf(agent);
              return (
                <li key={id}>
                  <button type="button" className={id === agentId ? "selected" : ""} onClick={() => { setAgentId(id); setThreadId(""); setAttached([]); }}>
                    <strong>{agentNameOf(agent)}</strong>
                    <small>{pick(agent, "status", "Status") || id}</small>
                  </button>
                </li>
              );
            })}
          </ul>
          <form className="manual" onSubmit={useManualAgent}>
            <label>
              Agent id
              <input value={manualAgentId} onChange={(event) => setManualAgentId(event.target.value)} placeholder="Paste an agent id" />
            </label>
            <button type="submit">Use id</button>
          </form>
        </aside>

        <section className="panel conversation">
          <div className="panel-head">
            <h2>Conversation</h2>
            <div className="row-actions">
              <button type="button" disabled={!agentId || busy === "thread"} onClick={() => onCreateThread("TEST")}>New test</button>
              <button type="button" className="ghost" disabled={!agentId || busy === "thread"} onClick={() => onCreateThread("PRODUCTION")}>New production</button>
            </div>
          </div>
          <div className="thread-row">
            {threads.length === 0 ? <p className="muted">No threads yet.</p> : null}
            {threads.map((thread) => {
              const id = String(pick(thread, "threadId"));
              return (
                <button key={id} type="button" className={id === threadId ? "chip selected" : "chip"} onClick={() => { setThreadId(id); setAttached([]); }}>
                  {pick(thread, "executionType")} · {pick(thread, "status")} · {shortId(id)}
                </button>
              );
            })}
          </div>

          <div className="transcript">
            {[...runs].reverse().map((run) => {
              const id = String(pick(run, "runId"));
              return (
                <article key={id} className={id === selectedRunId ? "turn selected" : "turn"} onClick={() => setSelectedRunId(id)}>
                  <header>
                    <span className={`status status-${String(pick(run, "status") || "").toLowerCase()}`}>{pick(run, "status")}</span>
                    <time>{formatWhen(pick(run, "createdAt"))}</time>
                  </header>
                  <p className="user-line">{pick(run, "input")}</p>
                  {pick(run, "output") ? <p className="assistant-line">{pick(run, "output")}</p> : null}
                  {pick(run, "error") ? <p className="error">{pick(run, "error")}</p> : null}
                </article>
              );
            })}
          </div>

          <form className="composer" onSubmit={onSend}>
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Message this agent" rows={3} disabled={!threadId} />
            <div className="composer-bar">
              <input ref={fileInput} type="file" onChange={(event) => setFile(event.target.files?.[0] || null)} disabled={!threadId} />
              <button type="button" className="ghost" disabled={!file || !threadId || busy === "upload"} onClick={onUpload}>
                {busy === "upload" ? "Uploading…" : "Attach file"}
              </button>
              <button type="submit" disabled={!threadId || !message.trim() || busy === "run"}>{busy === "run" ? "Running…" : "Send"}</button>
            </div>
            <div className="attached">
              {attached.map((item) => (
                <span key={item.artifactId} className="chip">{item.filename}</span>
              ))}
            </div>
            {notice ? <p className="notice">{notice}</p> : null}
            {error ? <p className="error">{error}</p> : null}
          </form>
        </section>

        <aside className="panel">
          <div className="panel-head">
            <h2>Run detail</h2>
          </div>
          {!selectedRun ? <p className="muted">Select a run to see status, steps, and files.</p> : null}
          {selectedRun ? (
            <dl className="facts">
              <div><dt>Run</dt><dd>{pick(selectedRun, "runId")}</dd></div>
              <div><dt>Status</dt><dd>{pick(selectedRun, "status")}</dd></div>
              <div><dt>Dispatch</dt><dd>{pick(selectedRun, "dispatch")}</dd></div>
              <div><dt>Attempt</dt><dd>{pick(selectedRun, "attempt") ?? 0}</dd></div>
              <div><dt>Stop</dt><dd>{pick(selectedRun, "stopReason") || "—"}</dd></div>
              <div><dt>Started</dt><dd>{formatWhen(pick(selectedRun, "startedAt")) || "—"}</dd></div>
              <div><dt>Finished</dt><dd>{formatWhen(pick(selectedRun, "completedAt")) || "—"}</dd></div>
              <div><dt>Input files</dt><dd>{(pick(selectedRun, "inputArtifactIds") || []).join(", ") || "—"}</dd></div>
              <div><dt>Output files</dt><dd>{(pick(selectedRun, "outputArtifactIds") || []).join(", ") || "—"}</dd></div>
              <div><dt>Steps</dt><dd>{(pick(selectedRun, "steps") || []).map(stepLabel).join(" → ") || "—"}</dd></div>
            </dl>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
