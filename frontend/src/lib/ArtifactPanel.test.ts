import { cleanup, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Artifact } from "./types";
import ArtifactPanel from "./components/ArtifactPanel.svelte";

const persistedArtifact: Artifact = {
  id: "artifact-1",
  title: "Private preview",
  type: "html",
  content_length: 10,
};

const unsafeHtml = `<!doctype html><html><head><style>h1{color:rgb(1,2,3)}</style></head><body>
<h1>Rendered artifact</h1><table><tbody><tr><td>Mercury</td></tr></tbody></table>
<script>window.__artifactExecuted = true</script><img src="https://example.invalid/track.png" onerror="alert(1)">
</body></html>`;

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("ArtifactPanel", () => {
  it("loads persisted HTML content, sanitizes active markup, and keeps a scriptless sandbox", async () => {
    localStorage.setItem("archon_token", "secret-token");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ ...persistedArtifact, content: unsafeHtml }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    render(ArtifactPanel, { props: { artifacts: [persistedArtifact] } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/artifacts/artifact-1");
    expect(new Headers(init?.headers).get("Authorization")).toBe(
      "Bearer secret-token",
    );

    const frame = await screen.findByTitle("Artifact preview");
    expect(frame.getAttribute("sandbox")).toBe("");
    await waitFor(() =>
      expect(frame.getAttribute("srcdoc")).toContain("Rendered artifact"),
    );
    const source = frame.getAttribute("srcdoc") || "";
    expect(source).toContain("default-src 'none'");
    expect(source).toContain("style-src 'unsafe-inline'");
    expect(source).toContain("<table>");
    expect(source).not.toContain("<script");
    expect(source).not.toContain("onerror=");
  });

  it("renders client-detected HTML without a network fetch", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const inlineArtifact: Artifact = {
      ...persistedArtifact,
      id: "local-html-1",
      content:
        "<!doctype html><html><body><h1>History artifact</h1></body></html>",
    };

    render(ArtifactPanel, { props: { artifacts: [inlineArtifact] } });

    const frame = screen.getByTitle("Artifact preview");
    await waitFor(() =>
      expect(frame.getAttribute("srcdoc")).toContain("History artifact"),
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(frame.getAttribute("sandbox")).toBe("");
  });
});
