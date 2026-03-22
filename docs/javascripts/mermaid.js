window.mermaidConfig = {
  startOnLoad: false,
  securityLevel: "loose",
  theme: "default",
};

function renderMermaidDiagrams() {
  if (typeof mermaid === "undefined") {
    return;
  }

  const codeBlocks = document.querySelectorAll(
    "pre code.language-mermaid, pre.mermaid code"
  );

  codeBlocks.forEach((codeBlock) => {
    const pre = codeBlock.parentElement;
    if (!pre || pre.dataset.mermaidProcessed === "true") {
      return;
    }

    const container = document.createElement("div");
    container.className = "mermaid";
    container.textContent = codeBlock.textContent || "";
    pre.replaceWith(container);
  });

  document.querySelectorAll(".mermaid").forEach((node) => {
    node.removeAttribute("data-processed");
  });

  mermaid.initialize(window.mermaidConfig);
  mermaid.run({
    querySelector: ".mermaid",
  });
}

if (typeof document$ !== "undefined" && document$.subscribe) {
  document$.subscribe(renderMermaidDiagrams);
} else {
  document.addEventListener("DOMContentLoaded", renderMermaidDiagrams);
  window.addEventListener("load", renderMermaidDiagrams);
}
