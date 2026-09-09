/*
 * auth.js — вхід через Google.
 *
 * Google дає одноразовий токен (живе ~годину). Ми одразу міняємо його на
 * сервері на власну «довгу» сесію (30 днів) — саме вона лежить у
 * localStorage і переживає перезавантаження сторінки.
 */

import { GOOGLE_CLIENT_ID, exchangeGoogleToken, loadSession, saveSession } from "./api.js";

let _onChange = () => {};
let _initialised = false;

/** Викликається після будь-якої зміни стану входу (увійшов / вийшов). */
export function onAuthChange(fn) { _onChange = fn; }

export function currentUser() { return loadSession(); }

function handleCredential(response) {
  exchangeGoogleToken(response.credential)
    .then((user) => { saveSession(user); _onChange(user); })
    .catch(() => { _onChange(loadSession()); });
}

/** Готує бібліотеку Google. Безпечно викликати один раз при старті. */
export function initAuth() {
  if (_initialised) return;
  _initialised = true;
  if (!GOOGLE_CLIENT_ID || typeof google === "undefined") return;
  google.accounts.id.initialize({
    client_id: GOOGLE_CLIENT_ID,
    callback: handleCredential,
    auto_select: false,
  });
}

/** Показує вікно входу Google. */
export function signIn() {
  if (!GOOGLE_CLIENT_ID || typeof google === "undefined") {
    alert("Вхід через Google ще не налаштовано на цьому сайті.");
    return;
  }
  google.accounts.id.cancel();
  google.accounts.id.prompt();
}

export function signOut() {
  saveSession(null);
  if (typeof google !== "undefined") google.accounts.id.disableAutoSelect();
  _onChange(null);
}
