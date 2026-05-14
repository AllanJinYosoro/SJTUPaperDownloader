const DEFAULTS = {
  headless: true,
  downloadDir: "",
  captchaModelPath: ""
};
const HOST_NAME = "paperdownloader.host";

let nativePort = null;
let connectPromise = null;
let nextRequestId = 1;
let lastSyncedConfig = "";
const pendingRequests = new Map();

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.sync.get(DEFAULTS);
  await chrome.storage.sync.set({ ...DEFAULTS, ...current });
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "sync") {
    return;
  }
  if (!("headless" in changes || "downloadDir" in changes || "captchaModelPath" in changes)) {
    return;
  }
  lastSyncedConfig = "";
  syncHostConfig().catch(() => {});
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
    headless: values.headless !== false,
    downloadDir: normalizeOptionalPath(values.downloadDir),
    captchaModelPath: normalizeOptionalPath(values.captchaModelPath)
  };
}

async function startDownload(payload) {
  const config = await settings();
  await syncHostConfig(config);
  return callHost("startDownload", {
    title: payload.title,
    scholarUrl: payload.scholarUrl,
    headless: config.headless
  });
}

async function getTask(taskId) {
  return callHost("getTask", { taskId });
}

async function submitCaptcha(taskId, text) {
  return callHost("submitCaptcha", { taskId, text });
}

async function health() {
  const config = await settings();
  await syncHostConfig(config);
  return callHost("health", {});
}

async function syncHostConfig(config = null) {
  const resolved = config || await settings();
  const serialized = JSON.stringify(resolved);
  if (serialized === lastSyncedConfig) {
    return;
  }
  const response = await callHost("updateConfig", {
    headless: resolved.headless,
    downloadDir: resolved.downloadDir,
    captchaModelPath: resolved.captchaModelPath
  });
  if (!response?.ok) {
    throw new Error(response?.error || "Could not sync host configuration");
  }
  lastSyncedConfig = serialized;
}

async function callHost(type, payload) {
  const port = await ensureNativePort();
  const id = `req-${Date.now()}-${nextRequestId++}`;
  return new Promise((resolve, reject) => {
    pendingRequests.set(id, { resolve, reject });
    try {
      port.postMessage({
        id,
        type,
        payload
      });
    } catch (error) {
      pendingRequests.delete(id);
      reject(error);
    }
  });
}

async function ensureNativePort() {
  if (nativePort) {
    return nativePort;
  }
  if (!connectPromise) {
    connectPromise = Promise.resolve().then(() => connectNativeHost());
  }
  return connectPromise;
}

function connectNativeHost() {
  const port = chrome.runtime.connectNative(HOST_NAME);
  port.onMessage.addListener(handleHostMessage);
  port.onDisconnect.addListener(() => {
    const reason = chrome.runtime.lastError?.message || "Native host disconnected";
    nativePort = null;
    connectPromise = null;
    lastSyncedConfig = "";
    rejectPending(reason);
  });
  nativePort = port;
  return port;
}

function handleHostMessage(message) {
  const id = message?.id;
  if (!id || !pendingRequests.has(id)) {
    return;
  }
  const { resolve } = pendingRequests.get(id);
  pendingRequests.delete(id);
  resolve({
    ok: message?.ok === true,
    data: message?.data ?? null,
    error: message?.error || null
  });
}

function rejectPending(reason) {
  for (const { reject } of pendingRequests.values()) {
    reject(new Error(reason));
  }
  pendingRequests.clear();
}

function normalizeOptionalPath(value) {
  return typeof value === "string" ? value.trim() : "";
}
