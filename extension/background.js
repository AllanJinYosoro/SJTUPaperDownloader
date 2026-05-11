const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8765",
  headless: true
};

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.sync.get(DEFAULTS);
  await chrome.storage.sync.set({ ...DEFAULTS, ...current });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handleMessage(message).then(sendResponse).catch((error) => {
    sendResponse({ ok: false, error: error.message || String(error) });
  });
  return true;
});

async function handleMessage(message) {
  if (message?.type === "startDownload") {
    return startDownload(message.payload);
  }
  if (message?.type === "getTask") {
    return getTask(message.taskId);
  }
  if (message?.type === "health") {
    return health();
  }
  return { ok: false, error: "Unknown message type" };
}

async function settings() {
  const values = await chrome.storage.sync.get(DEFAULTS);
  return {
    backendUrl: normalizeBackendUrl(values.backendUrl || DEFAULTS.backendUrl),
    headless: values.headless !== false
  };
}

async function startDownload(payload) {
  const config = await settings();
  const response = await fetch(`${config.backendUrl}/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload.title,
      scholar_url: payload.scholarUrl,
      headless: config.headless
    })
  });
  return parseResponse(response);
}

async function getTask(taskId) {
  const config = await settings();
  const response = await fetch(`${config.backendUrl}/tasks/${taskId}`);
  return parseResponse(response);
}

async function health() {
  const config = await settings();
  const response = await fetch(`${config.backendUrl}/health`);
  return parseResponse(response);
}

async function parseResponse(response) {
  let body = null;
  try {
    body = await response.json();
  } catch (_error) {
    body = {};
  }
  if (!response.ok) {
    return {
      ok: false,
      error: body.detail || body.error || `HTTP ${response.status}`
    };
  }
  return { ok: true, data: body };
}

function normalizeBackendUrl(value) {
  return String(value).replace(/\/+$/, "");
}

