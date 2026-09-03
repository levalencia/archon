import DOMPurify from "dompurify";
import type { Artifact } from "./types";

const PREVIEW_CSP =
  "default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:;";
const CSP_META = `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">`;

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function injectPreviewCsp(document: string): string {
  if (/<head(?:\s[^>]*)?>/i.test(document)) {
    return document.replace(
      /<head(?:\s[^>]*)?>/i,
      (head) => `${head}${CSP_META}`,
    );
  }
  if (/<html(?:\s[^>]*)?>/i.test(document)) {
    return document.replace(
      /<html(?:\s[^>]*)?>/i,
      (html) => `${html}<head>${CSP_META}</head>`,
    );
  }
  return `<!doctype html><html><head>${CSP_META}</head><body>${document}</body></html>`;
}

export function buildArtifactPreview(
  artifact: Pick<Artifact, "title" | "type" | "content">,
): string {
  const content = artifact.content || "";
  if (artifact.type !== "html") {
    return `<!doctype html><html><head>${CSP_META}<meta charset="utf-8"><style>body{margin:16px;background:#0d1117;color:#e6edf3;font-family:monospace;white-space:pre-wrap}pre{white-space:pre-wrap}</style></head><body><h1>${escapeHtml(artifact.title)}</h1><pre>${escapeHtml(content)}</pre></body></html>`;
  }

  const sanitized = DOMPurify.sanitize(content, {
    WHOLE_DOCUMENT: true,
    USE_PROFILES: { html: true },
    FORBID_TAGS: [
      "script",
      "iframe",
      "object",
      "embed",
      "form",
      "base",
      "meta",
    ],
    FORBID_ATTR: ["srcset", "formaction"],
    ALLOWED_URI_REGEXP: /^(?:(?:data|blob):|#)/i,
  });
  return injectPreviewCsp(sanitized);
}
