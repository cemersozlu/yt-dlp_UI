const urlInput = document.getElementById("url");
const folderInput = document.getElementById("folder");
const audioOnly = document.getElementById("audioOnly");
const downloadBtn = document.getElementById("downloadBtn");
const progressFill = document.getElementById("progressFill");
const pctEl = document.getElementById("pct");
const logEl = document.getElementById("log");
const liveStatusEl = document.getElementById("liveStatus");
const progressBarEl = document.querySelector(".progress-bar");

let pollTimer = null;
let lastNonProgressMessage = "";

fetch("/default_folder")
  .then(r => r.json())
  .then(data => {
    folderInput.value = data.folder;
  })
  .catch(() => {
    folderInput.value = "";
  });

function loadVersion() {
  fetch("/version")
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById("version");
      if (data.ready) {
        el.textContent = "v" + data.version;
      } else {
        // yt-dlp.exe still downloading / not found: retry shortly
        el.textContent = data.version;
        setTimeout(loadVersion, 2000);
      }
    })
    .catch(() => {
      document.getElementById("version").textContent = "";
    });
}
loadVersion();

function pasteUrl() {
  navigator.clipboard.readText()
    .then(text => {
      if (text) urlInput.value = text.trim();
    })
    .catch(() => {
      addLog("Clipboard access failed, paste manually.", "err");
    });
}

function addLog(msg, type = "") {
  const line = document.createElement("div");
  if (type) line.className = type;
  line.textContent = msg;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(text, type = "") {
  addLog(text, type);
}

function setLiveProgress(text) {
  liveStatusEl.textContent = text;
}

function setProgress(pct) {
  const n = Math.min(100, Math.max(0, Number(pct) || 0));
  progressFill.style.width = n + "%";
  if (pctEl) pctEl.textContent = n.toFixed(1).replace(/\.0$/, "") + "%";
  if (progressBarEl) progressBarEl.setAttribute("aria-valuenow", n);
}
function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollStatus(jobId) {
  try {
    const res = await fetch("/status/" + jobId);
    const data = await res.json();

    setProgress(data.percent || 0);
    if (!data.done && data.message) {
      if (/^Downloading/.test(data.message)) {
        setLiveProgress(data.message);
      } else if (data.message !== "Starting..." && data.message !== lastNonProgressMessage) {
        lastNonProgressMessage = data.message;
        addLog(data.message);
      }
    }

    if (data.done) {
      liveStatusEl.textContent = "";
      stopPoll();
      downloadBtn.disabled = false;
      if (data.ok) {
        setProgress(100);
        setStatus("Download finished.", "ok");
      } else {
        setStatus("Error", "err");
        addLog("Error: " + (data.error || "unknown"), "err");
      }
    }
  } catch (err) {
    stopPoll();
    downloadBtn.disabled = false;
    setStatus("Connection error", "err");
    addLog("Could not get status: " + err.message, "err")
  }
}

async function startDownload() {
  if (downloadBtn.disabled) return;

  const url = urlInput.value.trim();
  const folder = folderInput.value.trim();

  if (!url) {
    addLog("No URL entered.", "err");
    return;
  }

  stopPoll();
  downloadBtn.disabled = true;

  try {
    setProgress(0);
    setStatus("Starting...");
    liveStatusEl.textContent = "";
    lastNonProgressMessage = "";
    addLog("> " + url);

    const res = await fetch("/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url,
        folder: folder,
        audio_only: audioOnly.checked
      })
    });

    const data = await res.json();

    if (!data.ok || !data.job_id) {
      downloadBtn.disabled = false;
      setStatus("Error", "err");
      addLog("Error: " + (data.error || "could not start"), "err");
      return;
    }

    pollStatus(data.job_id);
    pollTimer = setInterval(() => pollStatus(data.job_id), 250);
  } catch (err) {
    downloadBtn.disabled = false;
    setStatus("Connection error", "err");
    addLog("Unexpected error: " + err.message, "err");
  }
}

urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") startDownload();
});

async function updateYtdlp() {
  const btn = document.getElementById("updateBtn");
  btn.disabled = true;
  setStatus("Updating yt-dlp...");
  addLog("yt-dlp update started...");

  try {
    const res = await fetch("/update", { method: "POST" });
    const data = await res.json();

    if (data.ok) {
      setStatus(data.message || "yt-dlp updated.", "ok");
      loadVersion();
    } else {
      setStatus("Update error", "err");
      addLog("Error: " + data.error, "err");
    }
  } catch (err) {
    setStatus("Connection error", "err");
    addLog("Could not reach server: " + err.message, "err");
  } finally {
    btn.disabled = false;
  }
}

// --- Debug bar: visual-only simulation of progress/status/log states. ---
// Does not touch the server or start any real download. Hidden by default,
// toggled with Ctrl+Alt+D.
function debugProgress(pct) {
  setProgress(pct);
}

function debugStatus(text, type = "") {
  setStatus(text, type);
}

function debugLog(msg, type = "") {
  addLog(msg, type);
}

function debugToggleDisabled() {
  downloadBtn.disabled = !downloadBtn.disabled;
}

function debugClearLog() {
  logEl.innerHTML = "";
}

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.altKey && e.key.toLowerCase() === "d") {
    e.preventDefault();
    document.getElementById("debugBar").classList.toggle("open");
  }
});
