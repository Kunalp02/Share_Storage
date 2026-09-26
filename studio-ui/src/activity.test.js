import assert from "node:assert/strict";
import test from "node:test";
import { buildActivity, durationLabel, fileLabel } from "./activity.js";

const now = Date.parse("2026-09-26T12:00:00Z");

test("activity summary counts live runs, recent failures, and active agents", () => {
  const activity = buildActivity({
    now,
    agents: [
      { agentId: "agent-1", name: "Claims" },
      { agentId: "agent-2", name: "Quiet" },
    ],
    threadsByAgent: {
      "agent-1": [
        { threadId: "thread-1", status: "OPEN", channel: "STUDIO", executionType: "TEST", triggeredBy: "ada" },
        { threadId: "thread-2", status: "OPEN", channel: "API", executionType: "PRODUCTION", deploymentId: "dep-1", triggeredBy: "api:claims-bot" },
      ],
      "agent-2": [
        { threadId: "thread-3", status: "EXPIRED", channel: "STUDIO", executionType: "TEST", triggeredBy: "ada" },
      ],
    },
    deploymentsByAgent: {
      "agent-1": [{ deploymentId: "dep-1", slug: "claims-bot" }],
    },
    runsByThread: {
      "agent-1:thread-1": [
        {
          runId: "run-live",
          status: "RUNNING",
          input: "What is open?",
          createdAt: "2026-09-26T11:50:00Z",
          attempt: 1,
          startedBy: "ada",
          clientIp: "10.4.4.4",
        },
      ],
      "agent-1:thread-2": [
        {
          runId: "run-fail",
          status: "FAILED",
          input: "Check claim",
          error: "model timeout",
          createdAt: "2026-09-26T11:00:00Z",
          startedAt: "2026-09-26T11:00:00Z",
          completedAt: "2026-09-26T11:00:12Z",
          attempt: 3,
          inputArtifactIds: ["file-1"],
          outputArtifactIds: [],
        },
        {
          runId: "run-old",
          status: "FAILED",
          input: "old",
          createdAt: "2026-09-20T11:00:00Z",
          completedAt: "2026-09-20T11:00:02Z",
        },
      ],
      "agent-2:thread-3": [
        { runId: "run-queue", status: "QUEUED", input: "waiting", createdAt: "2026-09-26T11:40:00Z" },
      ],
    },
  });

  assert.equal(activity.summary.running, 1);
  assert.equal(activity.summary.queued, 1);
  assert.equal(activity.summary.failedRecently, 1);
  assert.equal(activity.summary.activeAgents, 2);
  assert.equal(activity.rows[0].runId, "run-live");
  assert.equal(activity.rows[0].source, "Studio test");
  assert.equal(activity.rows[0].startedBy, "ada");
  assert.equal(activity.rows[0].clientIp, "10.4.4.4");
  assert.equal(activity.rows[0].agentName, "Claims");
  const failed = activity.rows.find((row) => row.runId === "run-fail");
  assert.equal(failed.source, "Published API");
  assert.equal(failed.slug, "claims-bot");
  assert.equal(failed.startedBy, "api:claims-bot");
  assert.equal(fileLabel(failed), "1 in");
  assert.equal(durationLabel(failed), "12s");
});
