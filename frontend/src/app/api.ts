export type Evidence = { source: string; path?: string | null; note?: string | null };

export type ChatResponse = {
  final_text: string;
  used_cloud: boolean;
  sensitive_detected: boolean;
  sanitized_cloud_query: string | null;
  extracted_public_terms: Record<string, unknown>;
  evidence: Evidence[];
  route: string;
};

export async function sendChat(
  user_text: string,
  allow_cloud: boolean,
  workspace_dirs: string[],
  preferred_files: string[]
): Promise<ChatResponse> {
  const res = await fetch("http://127.0.0.1:48155/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_text,
      allow_cloud,
      workspace_dirs,
      preferred_files,
    }),
  });

  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Backend error ${res.status}: ${txt}`);
  }

  const data: unknown = await res.json();
  if (typeof data !== "object" || data === null || !("final_text" in data)) {
    throw new Error("Invalid response from backend");
  }

  return data as ChatResponse;
}
