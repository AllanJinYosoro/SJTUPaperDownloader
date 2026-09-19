const DEFAULTS = {
  headless: true
};

const NATIVE_HOST_NAME = "com.sjtu.paperdownloader";

let startupPromise = null;

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
  if (message?.type === "submitCaptcha") {
    return submitCaptcha(message.taskId, message.text);
  }
  if (message?.type === "health") {
    return health();
  }
  return { ok: false, error: "Unknown message type" };
}

async function settings() {
  const values = await chrome.storage.sync.get(DEFAULTS);
  return {
    headless: values.headless !== false
  };
}

async function startDownload(payload) {
  const config = await settings();
  const service = await ensureLocalService();
  const response = await fetch(`${service.backendUrl}/download`, {
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
  const service = await ensureLocalService();
  const response = await fetch(`${service.backendUrl}/tasks/${taskId}`);
  return parseResponse(response);
}

async function submitCaptcha(taskId, text) {
  const service = await ensureLocalService();
  const response = await fetch(`${service.backendUrl}/tasks/${taskId}/captcha`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text })
  });
  return parseResponse(response);
}

async function health() {
  const service = await ensureLocalService();
  return {
    ok: true,
    data: {
      backend_url: service.backendUrl,
      service_started: service.serviceStarted,
      ...(service.health || {})
    }
  };
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

async function ensureLocalService() {
  if (!startupPromise) {
    startupPromise = sendNativeEnsureService().finally(() => {
      startupPromise = null;
    });
  }
  return startupPromise;
}

async function sendNativeEnsureService() {
  let response;
  try {
    response = await chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, {
      type: "ensureService"
    });
  } catch (error) {
    throw new Error(
      "Native host unavailable. Run scripts/install_native_host.ps1, then reload the extension."
    );
  }
  if (!response?.ok) {
    throw new Error(response?.error || "Local service could not be started");
  }
  return {
    backendUrl: normalizeBackendUrl(response.backendUrl),
    serviceStarted: Boolean(response.serviceStarted),
    health: response.health || {}
  };
}

function normalizeBackendUrl(value) {
  return String(value || "").replace(/\/+$/, "");
}
