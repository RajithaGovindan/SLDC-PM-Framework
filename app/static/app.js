/* Shared client helpers: Markdown + Mermaid rendering, clipboard, Alpine components. */
(function () {
  if (window.mermaid) {
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
  }
  if (window.marked) {
    marked.setOptions({ gfm: true, breaks: false });
  }

  let mermaidSeq = 0;

  async function renderMarkdown(el, md) {
    if (!el) return;
    const html = window.marked ? marked.parse(md || "") : (md || "");
    el.innerHTML = window.DOMPurify ? DOMPurify.sanitize(html) : html;
    const blocks = el.querySelectorAll("pre > code.language-mermaid");
    const nodes = [];
    blocks.forEach((code) => {
      const div = document.createElement("div");
      div.className = "mermaid";
      div.id = "mmd-" + (++mermaidSeq);
      div.textContent = code.textContent;
      code.parentElement.replaceWith(div);
      nodes.push(div);
    });
    if (nodes.length && window.mermaid) {
      try { await mermaid.run({ nodes }); }
      catch (e) { nodes.forEach((n) => n.classList.add("mermaid-error")); }
    }
  }

  async function copyText(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); ta.remove();
    }
    if (btn) {
      const old = btn.innerText;
      btn.innerText = "Copied!";
      setTimeout(() => (btn.innerText = old), 1400);
    }
  }

  window.SDLC = { renderMarkdown, copyText };

  // Render every static [data-markdown] block (source in a sibling <script type="text/markdown">).
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-md-src]").forEach((el) => {
      const src = document.getElementById(el.dataset.mdSrc);
      if (src) renderMarkdown(el, src.textContent);
    });
  });

  document.addEventListener("alpine:init", () => {
    Alpine.data("stageEditor", (cfg) => ({
      output: cfg.output,
      renderUrl: cfg.renderUrl,
      content: "",
      original: "",
      error: "",
      layout: "split",
      busy: false,
      init() {
        const src = document.getElementById("editor-initial");
        this.content = src ? JSON.parse(src.textContent) : "";
        this.original = this.content;
        this.$nextTick(() => this.refresh());
        window.addEventListener("beforeunload", (e) => {
          if (this.dirty && !this.busy) { e.preventDefault(); e.returnValue = ""; }
        });
      },
      get dirty() { return this.content !== this.original; },
      async refresh() {
        const el = this.$refs.preview;
        if (!this.content.trim()) { el.innerHTML = '<p class="text-slate-400 italic">Nothing to preview yet.</p>'; this.error = ""; return; }
        if (this.output === "markdown") { this.error = ""; return renderMarkdown(el, this.content); }
        try {
          const r = await fetch(this.renderUrl, { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: this.content }) });
          const data = await r.json();
          this.error = data.error || "";
          if (!data.error) await renderMarkdown(el, data.markdown);
        } catch (e) { this.error = "Preview failed: " + e; }
      },
      formatJson() {
        try { this.content = JSON.stringify(JSON.parse(this.content), null, 2); this.refresh(); }
        catch (e) { this.error = "Invalid JSON: " + e.message; }
      },
      submitting() { this.busy = true; },
    }));
  });
})();
