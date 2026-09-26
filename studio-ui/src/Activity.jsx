import { useEffect, useMemo, useState } from "react";
import { agentIdOf, asList, listAgents, listDeployments, listRuns, listThreads, pick } from "./api";
import { buildActivity, durationLabel, fileLabel, firstLine } from "./activity";

const STATUSES = ["All", "RUNNING", "QUEUED", "FAILED", "SUCCEEDED"];
const SOURCES = ["All", "Studio test", "Studio production", "Published API"];

function formatWhen(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function stepLabel(step) {
  if (!step) return "";
  if (typeof step === "string") return step;
  return step.name || step.detail || "";
}

async function loadActivity(token) {
  const agents = await listAgents(token);
  const threadsByAgent = {};
  const runsByThread = {};
  const deploymentsByAgent = {};
  await Promise.all(agents.map(async (agent) => {
    const agentId = agentIdOf(agent);
    if (!agentId) return;
    const [threads, deployments] = await Promise.all([
      listThreads(token, agentId).catch(() => []),
      listDeployments(token, agentId).catch(() => []),
    ]);
    const threadList = asList(threads).slice(0, 15);
    threadsByAgent[agentId] = threadList;
    deploymentsByAgent[agentId] = asList(deployments);
    await Promise.all(threadList.map(async (thread) => {
      const threadId = String(pick(thread, "threadId", "ThreadId") || "");
      if (!threadId) return;
      const runs = await listRuns(token, agentId, threadId).catch(() => []);
      runsByThread[`${agentId}:${threadId}`] = asList(runs).slice(0, 20);
    }));
  }));
  return buildActivity({ agents, threadsByAgent, runsByThread, deploymentsByAgent });
}

export function Activity({ session }) {
  const [activity, setActivity] = useState({ rows: [], summary: { running: 0, queued: 0, failedRecently: 0, activeAgents: 0 } });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("All");
  const [sourceFilter, setSourceFilter] = useState("All");
  const [agentFilter, setAgentFilter] = useState("All");
  const [selectedId, setSelectedId] = useState("");

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const next = await loadActivity(session.token);
      setActivity(next);
      setSelectedId((current) => current || (next.rows[0] ? next.rows[0].runId : ""));
    } catch (exc) {
      setError(exc.message || "Could not load activity.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [session.token]);

  const agents = useMemo(() => {
    const names = new Map();
    for (const row of activity.rows) names.set(row.agentId, row.agentName);
    return [...names.entries()];
  }, [activity.rows]);

  const visible = activity.rows.filter((row) => {
    if (statusFilter !== "All" && row.status !== statusFilter) return false;
    if (sourceFilter !== "All" && row.source !== sourceFilter) return false;
    if (agentFilter !== "All" && row.agentId !== agentFilter) return false;
    return true;
  });
  const selected = visible.find((row) => row.runId === selectedId) || visible[0] || null;

  return (
    <div className="activity">
      <section className="summary">
        <article><span>Running now</span><strong>{activity.summary.running}</strong></article>
        <article><span>Queued</span><strong>{activity.summary.queued}</strong></article>
        <article><span>Failed recently</span><strong>{activity.summary.failedRecently}</strong></article>
        <article><span>Active agents</span><strong>{activity.summary.activeAgents}</strong></article>
      </section>

      <div className="activity-body">
        <section className="panel activity-list">
          <div className="panel-head">
            <h2>Activity</h2>
            <button type="button" className="ghost" onClick={refresh}>{loading ? "Refreshing…" : "Refresh"}</button>
          </div>
          <div className="filters">
            <label>
              Status
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                {STATUSES.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label>
              Source
              <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
                {SOURCES.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label>
              Agent
              <select value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)}>
                <option>All</option>
                {agents.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
              </select>
            </label>
          </div>
          {error ? <p className="error">{error}</p> : null}
          {!loading && visible.length === 0 ? <p className="muted">No runs for the agents you can open.</p> : null}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Agent</th>
                  <th>Source</th>
                  <th>Who</th>
                  <th>Conversation</th>
                  <th>Status</th>
                  <th>Request</th>
                  <th>Result</th>
                  <th>Files</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={row.runId} className={selected?.runId === row.runId ? "selected" : ""} onClick={() => setSelectedId(row.runId)}>
                    <td>{formatWhen(row.createdAt)}</td>
                    <td>{row.agentName}</td>
                    <td>{row.source}</td>
                    <td>{row.startedBy}{row.clientIp ? ` · ${row.clientIp}` : ""}</td>
                    <td>{row.threadId.slice(0, 8)}</td>
                    <td><span className={`status status-${row.status.toLowerCase()}`}>{row.status}</span>{row.attempt > 1 ? ` · try ${row.attempt}` : ""}</td>
                    <td>{firstLine(row.input) || "—"}</td>
                    <td>{firstLine(row.error || row.output) || "—"}</td>
                    <td>{fileLabel(row)}</td>
                    <td>{durationLabel(row) || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="panel">
          <div className="panel-head"><h2>Run</h2></div>
          {!selected ? <p className="muted">Select a run.</p> : (
            <dl className="facts">
              <div><dt>Agent</dt><dd>{selected.agentName}</dd></div>
              <div><dt>Source</dt><dd>{selected.source}{selected.slug ? ` · ${selected.slug}` : ""}</dd></div>
              <div><dt>Started by</dt><dd>{selected.startedBy}</dd></div>
              <div><dt>Client IP</dt><dd>{selected.clientIp || "—"}</dd></div>
              <div><dt>Conversation</dt><dd>{selected.threadId}</dd></div>
              <div><dt>Status</dt><dd>{selected.status}{selected.attempt > 1 ? ` · attempt ${selected.attempt}` : ""}</dd></div>
              <div><dt>Dispatch</dt><dd>{selected.dispatch || "—"}</dd></div>
              <div><dt>Stop</dt><dd>{selected.stopReason || "—"}</dd></div>
              <div><dt>Message</dt><dd>{selected.input || "—"}</dd></div>
              <div><dt>Answer</dt><dd>{selected.output || "—"}</dd></div>
              <div><dt>Error</dt><dd>{selected.error || "—"}</dd></div>
              <div><dt>Input files</dt><dd>{selected.inputArtifactIds.join(", ") || "—"}</dd></div>
              <div><dt>Output files</dt><dd>{selected.outputArtifactIds.join(", ") || "—"}</dd></div>
              <div><dt>Steps</dt><dd>{selected.steps.map(stepLabel).filter(Boolean).join(" → ") || "—"}</dd></div>
            </dl>
          )}
        </aside>
      </div>
    </div>
  );
}
