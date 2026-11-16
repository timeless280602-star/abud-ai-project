export async function chatApi(path, method = "GET", body) {
  const response = await fetch("/web/chat" + path, {
    method, credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* Proxy errors may be HTML. */ }
    throw Error(typeof detail === "string" ? detail : "Request rejected. Please try again.");
  }
  return response;
}
