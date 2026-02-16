import { useEffect, useMemo, useState } from "react";
import { sendChat, type ChatResponse } from "./app/api";

type Msg = { role: "user" | "assistant"; text: string };

const LS = {
  workspaceDirs: "eurosec.workspaceDirs",
  preferredFile: "eurosec.preferredFile",
  allowCloud: "eurosec.allowCloud",
};

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function saveJson<T>(key: string, value: T): void {
  localStorage.setItem(key, JSON.stringify(value));
}

function isElectron(): boolean {
  return typeof window !== "undefined" && typeof window.eurosec !== "undefined";
}

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "assistant",
      text:
        "Hi! I'm EuroSec AI.\n\n" +
        "1) Choose workspace folder(s)\n" +
        "2) (Optional) Choose a file\n" +
        "3) Try: “Summarize this file” or “Rewrite this file into professional bullet points”",
    },
  ]);

  const [input, setInput] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [err, setErr] = useState<string | null>(null);

  // Persisted settings
  const [workspaceDirs, setWorkspaceDirs] = useState<string[]>(() =>
    loadJson<string[]>(LS.workspaceDirs, [])
  );
  const [preferredFile, setPreferredFile] = useState<string | null>(() =>
    loadJson<string | null>(LS.preferredFile, null)
  );
  const [allowCloud, setAllowCloud] = useState<boolean>(() =>
    loadJson<boolean>(LS.allowCloud, false)
  );

  const preferredFilesPayload = useMemo(
    () => (preferredFile ? [preferredFile] : []),
    [preferredFile]
  );

  // Save settings on change
  useEffect(() => saveJson(LS.workspaceDirs, workspaceDirs), [workspaceDirs]);
  useEffect(() => saveJson(LS.preferredFile, preferredFile), [preferredFile]);
  useEffect(() => saveJson(LS.allowCloud, allowCloud), [allowCloud]);

  // Backend metadata badges
  const [lastMeta, setLastMeta] = useState<
    Pick<ChatResponse, "route" | "used_cloud" | "sensitive_detected" | "sanitized_cloud_query"> | null
  >(null);

  // Auto-clear preferredFile if it’s not under current workspace folders (avoid confusion)
  useEffect(() => {
    if (!preferredFile) return;
    if (workspaceDirs.length === 0) return;

    const underAny = workspaceDirs.some((root) => preferredFile.startsWith(root));
    if (!underAny) {
      setPreferredFile(null);
    }
  }, [workspaceDirs, preferredFile]);

  async function chooseWorkspace(): Promise<void> {
    if (!isElectron()) {
      alert("Workspace picker works only in the Electron app (not in browser mode).");
      return;
    }
    const dir = await window.eurosec!.selectFolder();
    if (!dir) return;

    setWorkspaceDirs((prev) => {
      if (prev.includes(dir)) return prev;
      return [...prev, dir];
    });
  }

  async function chooseFile(): Promise<void> {
    if (!isElectron()) {
      alert("File picker works only in the Electron app (not in browser mode).");
      return;
    }
    const file = await window.eurosec!.selectFile();
    if (!file) return;

    // Helpful UX: ensure its folder is part of workspace
    const folder = file.includes("/") ? file.slice(0, file.lastIndexOf("/")) : null;

    if (folder && !workspaceDirs.some((d) => folder.startsWith(d))) {
      // If workspace empty, offer to add folder
      if (workspaceDirs.length === 0) {
        const ok = confirm(
          "You selected a file, but no workspace is configured.\n\n" +
            "Do you want to add the file's folder as a workspace automatically?\n" +
            folder
        );
        if (ok) setWorkspaceDirs([folder]);
      } else {
        const ok = confirm(
          "That file is outside your current workspace folders.\n\n" +
            "Do you want to add the file's folder to your workspace automatically?\n" +
            folder
        );
        if (ok) setWorkspaceDirs((prev) => (prev.includes(folder) ? prev : [...prev, folder]));
      }
    }

    setPreferredFile(file);
  }

  function removeWorkspace(dir: string): void {
    setWorkspaceDirs((prev) => prev.filter((x) => x !== dir));
  }

  function clearPermissions(): void {
    setWorkspaceDirs([]);
    setPreferredFile(null);
    setAllowCloud(false);
    setLastMeta(null);

    setMessages((m) => [
      ...m,
      { role: "assistant", text: "Permissions cleared. Please choose workspace folders again." },
    ]);
  }

  function clearChat(): void {
    setMessages([
      {
        role: "assistant",
        text:
          "Chat cleared.\n\nChoose a workspace and optionally a file.\nTry: “Summarize this file”",
      },
    ]);
    setErr(null);
    setLastMeta(null);
  }

  async function onSend(): Promise<void> {
    if (!input.trim() || busy) return;

    setErr(null);

    const userText = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", text: userText }]);

    // If they ask summarize/rewrite/tailor but no workspace -> fail fast
    const looksFileIntent = /(summarize|summary|rewrite|improve|tailor|bullet)/i.test(userText);
    if (looksFileIntent && workspaceDirs.length === 0) {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text:
            "Please choose at least one workspace folder first. " +
            "Then (optional) choose a file and ask again.",
        },
      ]);
      return;
    }

    setBusy(true);
    try {
      // Debug logs
      console.log("=== EuroSec DEBUG: Sending chat ===");
      console.log("userText:", userText);
      console.log("allowCloud:", allowCloud);
      console.log("workspaceDirs:", workspaceDirs);
      console.log("preferredFile:", preferredFile);
      console.log("preferred_files payload:", preferredFilesPayload);
      console.log("==================================");

      const resp = await sendChat(userText, allowCloud, workspaceDirs, preferredFilesPayload);

      setLastMeta({
        route: resp.route,
        used_cloud: resp.used_cloud,
        sensitive_detected: resp.sensitive_detected,
        sanitized_cloud_query: resp.sanitized_cloud_query,
      });

      setMessages((m) => [...m, { role: "assistant", text: resp.final_text }]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);

      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text:
            "Sorry — I couldn't reach the backend.\n\n" +
            "Check if it is running on http://127.0.0.1:48155 (try /health or /docs).",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const badge = (label: string) => (
    <span
      style={{
        fontSize: 12,
        padding: "4px 8px",
        borderRadius: 999,
        border: "1px solid #ddd",
        background: "#fff",
      }}
    >
      {label}
    </span>
  );

  return (
    <div style={{ fontFamily: "system-ui", maxWidth: 980, margin: "0 auto", padding: 24 }}>
      <h1 style={{ marginBottom: 12 }}>EuroSec AI</h1>

      {/* Control Panel */}
      <div
        style={{
          border: "1px solid #ddd",
          borderRadius: 12,
          padding: 14,
          background: "#fff",
          marginBottom: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button
              onClick={() => void chooseWorkspace()}
              style={{ padding: "8px 12px", borderRadius: 10, border: "1px solid #ddd" }}
            >
              Choose Workspace
            </button>

            <button
              onClick={() => void chooseFile()}
              style={{ padding: "8px 12px", borderRadius: 10, border: "1px solid #ddd" }}
            >
              Choose File (optional)
            </button>

            <label style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: 6 }}>
              <input
                type="checkbox"
                checked={allowCloud}
                onChange={(e) => setAllowCloud(e.target.checked)}
              />
              Allow Cloud (sanitized only)
            </label>

            <button
              onClick={clearPermissions}
              style={{ padding: "8px 12px", borderRadius: 10, border: "1px solid #ddd" }}
              title="Clear folders, file, and cloud toggle"
            >
              Clear Permissions
            </button>

            <button
              onClick={clearChat}
              style={{ padding: "8px 12px", borderRadius: 10, border: "1px solid #ddd" }}
              title="Clear chat messages"
            >
              Clear Chat
            </button>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {lastMeta?.route && badge(`Route: ${lastMeta.route}`)}
            {badge(`Cloud used: ${lastMeta?.used_cloud ? "yes" : "no"}`)}
            {badge(`Sensitive: ${lastMeta?.sensitive_detected ? "yes" : "no"}`)}
          </div>
        </div>

        <div style={{ marginTop: 10, fontSize: 12, color: "#444" }}>
          <div style={{ marginBottom: 6 }}>
            <b>Mode:</b> {isElectron() ? "Electron" : "Browser"}{" "}
            {!isElectron() && (
              <span style={{ color: "#b33" }}>
                (File/workspace selection is disabled in browser mode)
              </span>
            )}
          </div>

          <div style={{ marginBottom: 6 }}>
            <b>Workspaces:</b>{" "}
            {workspaceDirs.length ? (
              <span>
                {workspaceDirs.map((d) => (
                  <span key={d} style={{ marginRight: 8 }}>
                    <code>{d}</code>{" "}
                    <button
                      onClick={() => removeWorkspace(d)}
                      style={{
                        fontSize: 11,
                        padding: "2px 6px",
                        borderRadius: 8,
                        border: "1px solid #ddd",
                        cursor: "pointer",
                      }}
                      title="Remove this workspace"
                    >
                      remove
                    </button>
                  </span>
                ))}
              </span>
            ) : (
              "(none)"
            )}
          </div>

          <div>
            <b>Selected file:</b> {preferredFile ? <code>{preferredFile}</code> : "(none)"}
          </div>

          {allowCloud && (
            <div style={{ marginTop: 6, color: "#2a6" }}>
              Cloud is ON: only sanitized prompts go to the cloud. File content stays local.
              {lastMeta?.sanitized_cloud_query ? (
                <div style={{ marginTop: 4, color: "#555" }}>
                  <b>Last sanitized cloud query:</b>{" "}
                  <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
                    {lastMeta.sanitized_cloud_query}
                  </span>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>

      {/* Chat */}
      <div
        style={{
          border: "1px solid #ddd",
          borderRadius: 12,
          padding: 16,
          height: 460,
          overflowY: "auto",
          background: "#fff",
        }}
      >
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              marginBottom: 12,
              display: "flex",
              justifyContent: m.role === "user" ? "flex-end" : "flex-start",
            }}
          >
            <div
              style={{
                maxWidth: "78%",
                padding: "10px 12px",
                borderRadius: 12,
                background: m.role === "user" ? "#e7f0ff" : "#f3f3f3",
                whiteSpace: "pre-wrap",
              }}
            >
              {m.text}
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void onSend();
          }}
          placeholder='Try: "Summarize this file" or "Rewrite this file into professional bullet points"'
          style={{
            flex: 1,
            padding: 10,
            borderRadius: 10,
            border: "1px solid #ddd",
          }}
          disabled={busy}
        />
        <button
          onClick={() => void onSend()}
          disabled={busy}
          style={{
            padding: "10px 16px",
            borderRadius: 10,
            border: "1px solid #ddd",
            cursor: busy ? "not-allowed" : "pointer",
          }}
        >
          {busy ? "Sending..." : "Send"}
        </button>
      </div>

      {err && <div style={{ color: "crimson", marginTop: 10 }}>Error: {err}</div>}

      <div style={{ marginTop: 10, fontSize: 12, color: "#666" }}>
        Backend: http://127.0.0.1:48155 (try /health or /docs)
      </div>
    </div>
  );
}
