/*
 * theme.js — денна / нічна тема.
 *
 * За замовчуванням сайт слухає налаштування системи. Щойно людина
 * натискає кнопку — вибір запам'ятовується (localStorage) і система
 * більше не враховується, поки вибір не скинуть.
 *
 * Щоб не було «спалаху» неправильної теми при завантаженні, атрибут
 * data-theme на <html> ставиться крихітним скриптом прямо в <head>
 * (див. index.html) ще до того, як застосуються стилі.
 */

const KEY = "reab:theme";

function stored() {
  try { return localStorage.getItem(KEY); } catch (_e) { return null; }
}

/** Яка тема діє прямо зараз: "dark" або "light". */
export function effectiveTheme() {
  const s = stored();
  if (s === "dark" || s === "light") return s;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark" : "light";
}

/** Застосовує тему (або прибирає вибір, якщо передати null). */
export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "dark" || theme === "light") {
    root.setAttribute("data-theme", theme);
    try { localStorage.setItem(KEY, theme); } catch (_e) {}
  } else {
    root.removeAttribute("data-theme");
    try { localStorage.removeItem(KEY); } catch (_e) {}
  }
}

/** Перемикає день↔ніч, повертає нову тему. Додає короткий плавний перехід кольорів. */
export function toggleTheme() {
  const next = effectiveTheme() === "dark" ? "light" : "dark";
  const root = document.documentElement;
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!calm) {
    root.classList.add("theme-anim");
    window.setTimeout(() => root.classList.remove("theme-anim"), 340);
  }
  applyTheme(next);
  return next;
}
