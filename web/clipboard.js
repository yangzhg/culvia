window.CulviaClipboard = (() => {
  const root = typeof window !== "undefined" ? window : globalThis;

  async function writeText(value, environment = {}) {
    const text = String(value || "");
    if (!text) return false;

    const navigatorRef = environment.navigator || root.navigator;
    const documentRef = environment.document || root.document;
    if (navigatorRef?.clipboard?.writeText) {
      await navigatorRef.clipboard.writeText(text);
      return true;
    }

    if (!documentRef?.createElement || !documentRef?.body?.appendChild || !documentRef.execCommand) {
      return false;
    }

    const textarea = documentRef.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.inset = "0 auto auto 0";
    textarea.style.opacity = "0";
    documentRef.body.appendChild(textarea);
    if (textarea.select) textarea.select();
    try {
      return Boolean(documentRef.execCommand("copy"));
    } finally {
      if (textarea.remove) {
        textarea.remove();
      } else if (textarea.parentNode?.removeChild) {
        textarea.parentNode.removeChild(textarea);
      }
    }
  }

  return {
    writeText,
  };
})();
