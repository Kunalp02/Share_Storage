const SESSION_KEY = "studio.session";

export function loadSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}

export function pick(source, ...keys) {
  if (!source || typeof source !== "object") return undefined;
  for (const key of keys) {
    if (source[key] != null && source[key] !== "") return source[key];
  }
  return undefined;
}

export function asList(payload) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const key of ["items", "data", "agents", "value", "results"]) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}

export function agentIdOf(agent) {
  return String(pick(agent, "agentId", "id", "Id") || "");
}

export function agentNameOf(agent) {
  return String(pick(agent, "name", "Name") || agentIdOf(agent) || "Agent");
}

async function parseBody(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

export class ApiError extends Error {
  constructor(status, body) {
    const message = (body && (body.message || body.Message || body.title)) || `Request failed (${status})`;
    super(message);
    this.status = status;
    this.code = body && (body.code || body.Code);
    this.body = body;
  }
}

export async function request(path, { token, method = "GET", body, headers } = {}) {
  const finalHeaders = { ...(headers || {}) };
  if (token) finalHeaders.Authorization = `Bearer ${token}`;
  let payload = body;
  if (body != null && !(body instanceof FormData) && typeof body !== "string") {
    finalHeaders["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, { method, headers: finalHeaders, body: payload });
  } catch {
    throw new ApiError(503, { message: "The service behind this call is unreachable." });
  }
  const parsed = await parseBody(response);
  if (!response.ok) {
    if (!parsed || (!parsed.message && !parsed.Message && !parsed.title && !parsed.code)) {
      throw new ApiError(response.status, { message: `The service behind this call returned ${response.status}.` });
    }
    throw new ApiError(response.status, parsed);
  }
  return parsed;
}

export function login(username, password) {
  return request("/platform/auth/api/v1/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

export function logout(token) {
  return request("/platform/auth/api/v1/auth/logout", { method: "POST", token });
}

export function me(token) {
  return request("/platform/auth/api/v1/auth/me", { token });
}

export async function listAgents(token) {
  const payload = await request("/platform/agents/api/v1/agents", { token });
  return asList(payload);
}

export function listThreads(token, agentId) {
  return request(`/platform/execution/api/v1/agents/${agentId}/threads`, { token });
}

export function createThread(token, agentId, executionType) {
  return request(`/platform/execution/api/v1/agents/${agentId}/threads`, {
    method: "POST",
    token,
    body: { executionType },
  });
}

export function listRuns(token, agentId, threadId) {
  return request(`/platform/execution/api/v1/agents/${agentId}/threads/${threadId}/runs`, { token });
}

export function startRun(token, agentId, threadId, input, inputArtifactIds) {
  return request(`/platform/execution/api/v1/agents/${agentId}/threads/${threadId}/runs`, {
    method: "POST",
    token,
    body: { input, inputArtifactIds, stream: false, background: false },
  });
}

export function initArtifact(token, agentId, threadId, file) {
  return request(`/platform/storage/api/v1/agents/${agentId}/artifacts/init`, {
    method: "POST",
    token,
    body: {
      threadId,
      artifactType: "INPUT",
      filename: file.name,
      contentType: file.type || "application/octet-stream",
      mode: "TEST",
    },
  });
}

export async function uploadArtifact(token, agentId, threadId, file) {
  const init = await initArtifact(token, agentId, threadId, file);
  const uploadUrl = pick(init, "uploadUrl", "UploadUrl");
  const artifactId = pick(init, "artifactId", "ArtifactId");
  if (!uploadUrl || !artifactId) {
    throw new ApiError(502, { message: "Storage did not return an upload URL." });
  }
  const put = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!put.ok) {
    throw new ApiError(put.status, { message: "File upload to storage was rejected. Check MinIO CORS if this is a browser error." });
  }
  const completed = await request(`/platform/storage/api/v1/artifacts/${artifactId}/complete`, {
    method: "POST",
    token,
    body: { sizeBytes: file.size },
  });
  return { artifactId: String(artifactId), filename: file.name, completed };
}
