window.CulviaApi = (() => {
  function t(key, params = {}, fallback = "") {
    const api = window.CulviaI18n;
    const value = api?.t ? api.t(key, params) : key;
    return value === key && fallback ? fallback : value;
  }

  async function readError(response) {
    const text = await response.text();
    return text || response.statusText;
  }

  async function jsonResponse(response) {
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    return response.json();
  }

  function postJson(url, data = {}) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then(jsonResponse);
  }

  function getJson(url) {
    return fetch(url).then(jsonResponse);
  }

  function uploadForm(url, form) {
    return fetch(url, { method: "POST", body: form }).then(jsonResponse);
  }

  function errorMessage(error) {
    const message = error?.message || t("common.operationFailed", {}, "Operation failed");
    try {
      const parsed = JSON.parse(message);
      if (parsed?.errorCode) {
        return t(`apiError.${parsed.errorCode}`, parsed.errorParams || {}, parsed.error || message);
      }
      return parsed.error || message;
    } catch (_error) {
      return message;
    }
  }

  return {
    errorMessage,
    getJson,
    postJson,
    uploadForm,
  };
})();
