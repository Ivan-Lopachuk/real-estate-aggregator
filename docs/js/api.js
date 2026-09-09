/*
 * api.js — увесь зв'язок дошки із сервером (server/app.py) в одному місці.
 *
 * Тут:
 *   • адреса сервера й Google Client ID (це не секрети — можна тримати в коді);
 *   • зберігання сесії користувача в localStorage;
 *   • тонкі обгортки над fetch для кожного ендпоїнта.
 *
 * Помилки не «ковтаються»: кожна обгортка кидає Error з людським
 * повідомленням, а хто викликав — сам вирішує, що показати.
 */

// Адреса твого сервера на Render. Заповнюється один раз після деплою
// (див. SETUP-SERVER.md). Решта адрес — поруч із /api/chat.
export const BACKEND_ORIGIN = "https://real-estate-aggregator-gmes.onrender.com";

// Client ID застосунку «Увійти через Google» (Google Cloud Console).
// Публічний за задумом. Поки порожній — кнопка входу просто не працює.
export const GOOGLE_CLIENT_ID =
  "810718646832-otce2khredrh1t6r241fq878cs5bsknt.apps.googleusercontent.com";

const API = (path) => `${BACKEND_ORIGIN}/api${path}`;

// --- сесія користувача --------------------------------------------------

const SESSION_KEY = "reab:google-user"; // { sub, email, name, picture, session_token }

export function loadSession() {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY)); }
  catch (_e) { return null; }
}

export function saveSession(user) {
  try {
    if (user) localStorage.setItem(SESSION_KEY, JSON.stringify(user));
    else localStorage.removeItem(SESSION_KEY);
  } catch (_e) { /* приватний режим — просто не запам'ятаємо */ }
}

function authHeader() {
  const u = loadSession();
  return u && u.session_token ? { Authorization: `Bearer ${u.session_token}` } : {};
}

/**
 * Обгортка над fetch: додає токен, розбирає JSON, кидає зрозумілу
 * помилку. Особливий стан 401 (сесія протухла) і 402 (немає підписки)
 * позначаємо в err.code, щоб виклик міг зреагувати правильно.
 */
async function request(path, { method = "GET", body } = {}) {
  let resp;
  try {
    resp = await fetch(API(path), {
      method,
      headers: {
        "Content-Type": "application/json",
        ...authHeader(),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (_e) {
    const err = new Error(
      "Не вдалося зв'язатися із сервером. Якщо він давно не працював, " +
      "спробуй ще раз за хвилину — безкоштовний сервер міг «засинати»."
    );
    err.code = "network";
    throw err;
  }

  let data = null;
  try { data = await resp.json(); } catch (_e) { /* тіло не JSON */ }

  if (!resp.ok) {
    const err = new Error((data && data.error) || `Сервер відповів помилкою (${resp.status}).`);
    if (resp.status === 401) err.code = "unauthorized";
    else if (resp.status === 402) err.code = "no_subscription";
    else if (resp.status === 403) err.code = "forbidden";
    throw err;
  }
  return data || {};
}

// --- вхід --------------------------------------------------------------

/** Обмінює одноразовий токен Google на «довгу» сесію (30 днів). */
export function exchangeGoogleToken(idToken) {
  return request("/auth/google", { method: "POST", body: { id_token: idToken } });
}

/** «Хто я і що мені дозволено» — { user, entitlement }. */
export function fetchMe() {
  return request("/me");
}

// --- AI-пошук ---------------------------------------------------------

export function chatSearch(message, history) {
  return request("/chat", { method: "POST", body: { message, history } });
}

// --- розсилка --------------------------------------------------------

export const getSubscription = () => request("/subscription");
export const saveSubscription = (body) => request("/subscription", { method: "POST", body });
export const cancelSubscription = () => request("/subscription", { method: "DELETE" });

// --- стрічка сповіщень у кабінеті ------------------------------------

export const getFeed = () => request("/feed");
export const markFeedRead = (body) => request("/feed/read", { method: "POST", body });

// --- запит доступу (для тих, у кого немає підписки) ------------------

export const requestAccess = (message) =>
  request("/access-request", { method: "POST", body: { message } });

// --- панель адміна --------------------------------------------------

export const adminListSubscriptions = () => request("/admin/subscriptions");
export const adminGrantSubscription = (body) =>
  request("/admin/subscriptions", { method: "POST", body });
export const adminRevokeSubscription = (email) =>
  request("/admin/subscriptions", { method: "DELETE", body: { email } });
export const adminListAccessRequests = () => request("/admin/access-requests");

// --- синхронізація «переглянуто» / «обране» між пристроями ----------

export const getSeen = () => request("/seen");
export const putSeen = (seen) => request("/seen", { method: "POST", body: { seen } });
export const getFavorites = () => request("/favorites");
export const putFavorites = (favorites) =>
  request("/favorites", { method: "POST", body: { favorites } });
