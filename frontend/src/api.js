const KEY = "portal_token";
export const getToken = () => localStorage.getItem(KEY) || "";
export const setToken = (t) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY));

async function request(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/auth/login") {
    setToken("");
    window.dispatchEvent(new Event("portal:logout"));
  }
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b = {}) => request("POST", p, b),
  put: (p, b = {}) => request("PUT", p, b),
};

export const fileToBase64 = (file) =>
  new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1]);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
