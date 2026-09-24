// Monaco-backed code editor, with the plain textarea as its fallback.
//
// The exercise page needs a real coding surface — syntax highlighting,
// indentation, bracket matching — not a text box. Monaco is what the online
// judges use, so it is what is mounted here.
//
// The textarea it replaces stays in the DOM and stays in sync: every caller
// still reads and writes `textarea.value`, and if Monaco cannot be reached
// (no network, blocked CDN) the textarea is simply unhidden and used as it
// always was. The page is never left without somewhere to type.
window.CodeEditor = (function () {
  // Same build and CDN the notebook already loads, so a student who has used
  // one page has the other in cache.
  const CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs";
  // Monaco is a large download. Past this, stop waiting and show the textarea
  // rather than leaving the student staring at an empty panel.
  const LOAD_TIMEOUT_MS = 8000;

  function prefersDark() {
    const declared = document.documentElement.getAttribute("data-theme");
    if (declared === "dark") return true;
    if (declared === "light") return false;
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function themeName() {
    return prefersDark() ? "plp-dark" : "plp-light";
  }

  // Monaco ships vs / vs-dark, whose greys are close to but not the same as
  // this app's surfaces. Matching them stops the editor reading as a panel
  // pasted in from somewhere else.
  let themed = false;
  function defineThemes(monaco) {
    if (themed) return;
    themed = true;
    monaco.editor.defineTheme("plp-light", {
      base: "vs",
      inherit: true,
      rules: [
        { token: "comment", foreground: "5f6368", fontStyle: "italic" },
        { token: "keyword", foreground: "1967d2" },
        { token: "string", foreground: "188038" },
        { token: "number", foreground: "b06000" },
      ],
      colors: {
        "editor.background": "#eef2f7",
        "editorGutter.background": "#eef2f7",
        "editorLineNumber.foreground": "#94a3b8",
        "editor.lineHighlightBackground": "#e4eaf3",
      },
    });
    monaco.editor.defineTheme("plp-dark", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "comment", foreground: "6b7a8d", fontStyle: "italic" },
        { token: "keyword", foreground: "7cb8ff" },
        { token: "string", foreground: "6fd47e" },
        { token: "number", foreground: "e3b341" },
      ],
      colors: {
        "editor.background": "#0a0d12",
        "editorGutter.background": "#0a0d12",
        "editorLineNumber.foreground": "#4b5666",
        "editor.lineHighlightBackground": "#111722",
      },
    });
  }

  function loadMonaco() {
    if (window.monaco && window.monaco.editor) return Promise.resolve(window.monaco);
    const amdRequire = window.require;
    if (!amdRequire || typeof amdRequire.config !== "function") {
      return Promise.reject(new Error("Monaco loader unavailable"));
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Monaco load timed out")), LOAD_TIMEOUT_MS);
      // Monaco's workers are same-origin only; served from a CDN they must be
      // bootstrapped through a blob that re-points the loader at that CDN.
      window.MonacoEnvironment = {
        getWorkerUrl() {
          const shim = `self.MonacoEnvironment = { baseUrl: "${CDN}/" };
                        importScripts("${CDN}/base/worker/workerMain.js");`;
          return URL.createObjectURL(new Blob([shim], { type: "text/javascript" }));
        },
      };
      amdRequire.config({ paths: { vs: CDN } });
      amdRequire(
        ["vs/editor/editor.main"],
        () => {
          clearTimeout(timer);
          resolve(window.monaco);
        },
        (err) => {
          clearTimeout(timer);
          reject(err);
        }
      );
    });
  }

  // Everything the textarea already did, for the fallback path: Tab indents
  // instead of leaving the field, Escape is the keyboard way out (WCAG 2.1.2).
  function wireTextarea(textarea, onChange) {
    textarea.addEventListener("input", onChange);
    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Escape") return textarea.blur();
      if (e.key !== "Tab" || e.shiftKey) return;
      e.preventDefault();
      textarea.setRangeText("    ", textarea.selectionStart, textarea.selectionEnd, "end");
      onChange();
    });
  }

  function textareaAdapter(host, textarea, onChange) {
    if (host) host.hidden = true;
    textarea.hidden = false;
    wireTextarea(textarea, onChange);
    return {
      monaco: false,
      getValue: () => textarea.value,
      setValue: (v) => {
        textarea.value = v;
      },
      setReadOnly: (ro) => {
        textarea.readOnly = ro;
      },
      focus: () => textarea.focus(),
    };
  }

  /**
   * Mount an editor over `textarea`, rendering into `host`.
   * Resolves once one of the two is live; it never rejects.
   */
  function mount({ host, textarea, language = "python", onChange = () => {} }) {
    return loadMonaco().then(
      (monaco) => {
        defineThemes(monaco);
        const editor = monaco.editor.create(host, {
          value: textarea.value,
          language,
          theme: themeName(),
          automaticLayout: true,
          fontSize: 13.5,
          fontFamily:
            getComputedStyle(document.documentElement).getPropertyValue("--mono") ||
            "monospace",
          tabSize: 4,
          insertSpaces: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          renderLineHighlight: "all",
          smoothScrolling: true,
          padding: { top: 12, bottom: 12 },
        });

        // The textarea stays the value everyone else reads.
        editor.onDidChangeModelContent(() => {
          textarea.value = editor.getValue();
          onChange();
        });

        // Follow the page when the theme changes underneath us.
        const media = window.matchMedia("(prefers-color-scheme: dark)");
        const retheme = () => monaco.editor.setTheme(themeName());
        if (media.addEventListener) media.addEventListener("change", retheme);
        new MutationObserver(retheme).observe(document.documentElement, {
          attributes: true,
          attributeFilter: ["data-theme"],
        });

        return {
          monaco: true,
          getValue: () => editor.getValue(),
          setValue: (v) => {
            if (editor.getValue() !== v) editor.setValue(v);
            textarea.value = v;
          },
          setReadOnly: (ro) => editor.updateOptions({ readOnly: ro }),
          focus: () => editor.focus(),
        };
      },
      () => textareaAdapter(host, textarea, onChange)
    );
  }

  return { mount };
})();
