import { agentIdOf, agentNameOf, pick } from "./api.js";

const DAY_MS = 24 * 60 * 60 * 1000;

export function sourceOf(thread) {
  const channel = String(pick(thread, "channel", "Channel") || "");
  const executionType = String(pick(thread, "executionType", "ExecutionType") || "");
  if (channel === "API" || pick(thread, "deploymentId", "DeploymentId")) return "Published API";
  if (executionType === "PRODUCTION") return "Studio production";
  return "Studio test";
}

export function startedBy(run, thread, source, slug) {
  const who = pick(run, "startedBy", "StartedBy") || pick(thread, "triggeredBy", "TriggeredBy");
  if (who) return String(who);
  if (source === "Published API") return slug ? `api:${slug}` : "Published API";
  return "Studio";
}

export function firstLine(text, max = 90) {
  const line = String(text || "").split("\n")[0].trim();
  if (!line) return "";
  return line.length > max ? `${line.slice(0, max)}…` : line;
}

export function fileLabel(row) {
  const incoming = (row.inputArtifactIds || []).length;
  const outgoing = (row.outputArtifactIds || []).length;
  if (!incoming && !outgoing) return "—";
  const parts = [];
  if (incoming) parts.push(`${incoming} in`);
  if (outgoing) parts.push(`${outgoing} out`);
  return parts.join(" · ");
}

function stamp(value) {
  const ms = new Date(value || 0).getTime();
  return Number.isNaN(ms) ? 0 : ms;
}

export function durationLabel(row) {
  const start = stamp(row.startedAt || row.createdAt);
  const end = stamp(row.completedAt);
  if (!start || !end || end < start) return "";
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function buildActivity({ agents, threadsByAgent, runsByThread, deploymentsByAgent, now = Date.now() }) {
  const names = new Map((agents || []).map((agent) => [agentIdOf(agent), agentNameOf(agent)]));
  const rows = [];
  const openAgents = new Set();

  for (const [agentId, threads] of Object.entries(threadsByAgent || {})) {
    const deployments = deploymentsByAgent?.[agentId] || [];
    const slugByDeployment = new Map(
      deployments.map((item) => [String(pick(item, "deploymentId", "DeploymentId") || ""), String(pick(item, "slug", "Slug") || "")]),
    );
    for (const thread of threads || []) {
      if (String(pick(thread, "status", "Status") || "") === "OPEN") openAgents.add(agentId);
      const threadId = String(pick(thread, "threadId", "ThreadId") || "");
      const source = sourceOf(thread);
      const slug = slugByDeployment.get(String(pick(thread, "deploymentId", "DeploymentId") || "")) || "";
      const runs = runsByThread?.[`${agentId}:${threadId}`] || [];
      for (const run of runs) {
        rows.push({
          runId: String(pick(run, "runId", "RunId") || ""),
          threadId,
          agentId,
          agentName: names.get(agentId) || agentId,
          status: String(pick(run, "status", "Status") || ""),
          dispatch: String(pick(run, "dispatch", "Dispatch") || ""),
          input: String(pick(run, "input", "Input") || ""),
          output: String(pick(run, "output", "Output") || ""),
          error: String(pick(run, "error", "Error") || ""),
          attempt: Number(pick(run, "attempt", "Attempt") || 0),
          stopReason: String(pick(run, "stopReason", "StopReason") || ""),
          steps: pick(run, "steps", "Steps") || [],
          inputArtifactIds: pick(run, "inputArtifactIds", "InputArtifactIds") || [],
          outputArtifactIds: pick(run, "outputArtifactIds", "OutputArtifactIds") || [],
          createdAt: pick(run, "createdAt", "CreatedAt"),
          startedAt: pick(run, "startedAt", "StartedAt"),
          completedAt: pick(run, "completedAt", "CompletedAt"),
          source,
          slug,
          startedBy: startedBy(run, thread, source, slug),
          clientIp: String(pick(run, "clientIp", "ClientIp") || ""),
          threadStatus: String(pick(thread, "status", "Status") || ""),
        });
      }
    }
  }

  rows.sort((left, right) => stamp(right.createdAt) - stamp(left.createdAt));
  const recent = (row) => {
    const when = stamp(row.completedAt || row.createdAt);
    return when > 0 && now - when <= DAY_MS;
  };
  const active = new Set(openAgents);
  for (const row of rows) {
    if (recent(row)) active.add(row.agentId);
  }
  return {
    rows,
    summary: {
      running: rows.filter((row) => row.status === "RUNNING").length,
      queued: rows.filter((row) => row.status === "QUEUED").length,
      failedRecently: rows.filter((row) => row.status === "FAILED" && recent(row)).length,
      activeAgents: active.size,
    },
  };
}
