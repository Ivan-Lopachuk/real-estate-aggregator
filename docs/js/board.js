/*
 * board.js — головна дошка: рядок AI-пошуку + список знайдених квартир.
 *
 * Що показуємо (mode):
 *   "home"      — порожня головна з підказкою «Почни з пошуку»;
 *   "search"    — результати останнього AI-пошуку;
 *   "since"     — відкрито за посиланням з листа (?since= або ?ids=);
 *   "favorites" — лише додані в обране (⭐).
 *
 * Позначки «переглянуто» й «обране» зберігаються в цьому браузері, а
 * для залогінених ще й синхронізуються між пристроями через сервер.
 */

import {
  chatSearch, getSeen, putSeen, getFavorites, putFavorites, loadSession,
} from "./api.js";
import {
  el, clear, icon, fmtPrice, fmtWhen, siteLabel, displayTitle, metaLine, buildMapLink, toast,
} from "./ui.js";

const SEEN_KEY = "reab:opened";
const FAV_KEY = "reab:favorites";

const SUGGESTIONS = [
  "квартира в Генті до 800€",
  "будинок в Антверпені, 3 спальні",
  "квартира в Мерксемі за останні 3 дні",
  "від 60 м² у Кортрейку до 900€",
];

let DATA = null;               // вміст data.json (для "since"/"favorites")
let searchResults = [];
let chatHistory = [];
let mode = "home";
let onlyUnseen = false;
let sortBy = "date";
let rootEl = null;

const params = new URLSearchParams(location.search);
const sinceFilter = params.get("since");
const idsFilter = params.get("ids");
const idsSet = idsFilter ? new Set(idsFilter.split(",")) : null;

// --- localStorage: «переглянуто» / «обране» --------------------------

const readMap = (key) => { try { return JSON.parse(localStorage.getItem(key)) || {}; } catch (_e) { return {}; } };
const writeMap = (key, m) => { try { localStorage.setItem(key, JSON.stringify(m)); } catch (_e) {} };

const isSeen = (uid) => Object.prototype.hasOwnProperty.call(readMap(SEEN_KEY), uid);
function setSeen(uid, on) {
  const m = readMap(SEEN_KEY);
  if (on) m[uid] = new Date().toISOString(); else delete m[uid];
  writeMap(SEEN_KEY, m);
  scheduleSync("seen");
}
const isFav = (uid) => Object.prototype.hasOwnProperty.call(readMap(FAV_KEY), uid);
function setFav(uid, on) {
  const m = readMap(FAV_KEY);
  if (on) m[uid] = new Date().toISOString(); else delete m[uid];
  writeMap(FAV_KEY, m);
  scheduleSync("fav");
}

// --- синхронізація з сервером (тихо, з невеликою затримкою) -----------

const timers = {};
function scheduleSync(kind) {
  if (!loadSession()) return;
  clearTimeout(timers[kind]);
  timers[kind] = setTimeout(() => {
    const push = kind === "seen"
      ? putSeen(readMap(SEEN_KEY))
      : putFavorites(readMap(FAV_KEY));
    push.catch(() => { /* фонова синхронізація — мовчазна невдача */ });
  }, 2500);
}

export function syncFromServer() {
  if (!loadSession()) return;
  getSeen().then((d) => {
    writeMap(SEEN_KEY, Object.assign({}, d.seen || {}, readMap(SEEN_KEY)));
    scheduleSync("seen");
    if (rootEl) render();
  }).catch(() => {});
  getFavorites().then((d) => {
    writeMap(FAV_KEY, Object.assign({}, d.favorites || {}, readMap(FAV_KEY)));
    scheduleSync("fav");
    if (rootEl) render();
  }).catch(() => {});
}

// --- дані ------------------------------------------------------------

export function loadData() {
  return fetch("data.json?" + Date.now())
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
    .then((d) => { DATA = d; return d; })
    .catch(() => { DATA = { listings: [] }; });
}

function baseMode() {
  if (sinceFilter || idsSet) return "since";
  if (searchResults.length) return "search";
  return "home";
}

function currentBase() {
  if (mode === "search") return searchResults;
  if (mode === "favorites") return (DATA?.listings || []).filter((l) => isFav(l.uid));
  if (mode === "since") {
    const list = DATA?.listings || [];
    if (idsSet) return list.filter((l) => idsSet.has(l.uid));
    return list.filter((l) => l.first_seen_utc >= sinceFilter);
  }
  return [];
}

function sortItems(items) {
  const withPrice = items.filter((l) => l.price != null);
  const withoutPrice = items.filter((l) => l.price == null);
  if (sortBy === "price_asc") withPrice.sort((a, b) => a.price - b.price);
  else if (sortBy === "price_desc") withPrice.sort((a, b) => b.price - a.price);
  else return items;
  return withPrice.concat(withoutPrice);
}

// --- картка оголошення ---------------------------------------------

function card(l) {
  const seen = isSeen(l.uid);
  const node = el("article", { class: "listing" + (seen ? " listing--seen" : "") });

  if (l.photo_url) {
    const img = el("img", { class: "listing__photo", src: l.photo_url, alt: "", loading: "lazy" });
    const thumb = el("a", {
      class: "listing__thumb", href: l.url, target: "_blank", rel: "noopener",
      onclick: () => markSeen(l),
    }, [img]);
    img.addEventListener("error", () => thumb.remove());
    node.appendChild(thumb);
  }

  const badges = [el("span", { class: "badge badge--new", text: "нове" })];
  if (l.fiber_available === true) {
    badges.push(el("span", { class: "badge badge--fiber" }, [
      icon("bolt", { size: 12, filled: true }), "Оптика Proximus",
    ]));
  }
  if (l.price_previous != null && l.price != null && l.price_previous !== l.price) {
    const down = l.price < l.price_previous;
    badges.push(el("span", {
      class: "badge " + (down ? "badge--down" : "badge--up"),
      text: (down ? "⬇ було " : "⬆ було ") + fmtPrice(l.price_previous, l.currency),
    }));
  }

  const alsoOn = (l.also_on || []).length
    ? el("div", { class: "listing__also" }, [
        "Також на: ",
        ...l.also_on.flatMap((o, i) => {
          const a = el("a", { href: o.url, target: "_blank", rel: "noopener", text: siteLabel(o.url) });
          return i ? [", ", a] : [a];
        }),
      ])
    : null;

  const actions = el("div", { class: "listing__actions" }, [
    el("a", {
      class: "btn btn-primary btn-sm", href: l.url, target: "_blank", rel: "noopener",
      text: "Відкрити на " + siteLabel(l.url), onclick: () => markSeen(l),
    }),
    buildMapLink(l),
    el("button", {
      class: "btn btn-ghost btn-sm",
      text: seen ? "Повернути в нові" : "Позначити переглянутим",
      onclick: () => { setSeen(l.uid, !seen); render(); },
    }),
  ]);

  const star = el("button", {
    class: "listing__star" + (isFav(l.uid) ? " is-on" : ""),
    text: "★",
    title: isFav(l.uid) ? "В обраному — натисни, щоб прибрати" : "Додати в обране",
    "aria-label": isFav(l.uid) ? "Прибрати з обраного" : "Додати в обране",
    onclick: () => { setFav(l.uid, !isFav(l.uid)); render(); },
  });

  const body = el("div", { class: "listing__body" }, [
    el("div", { class: "listing__top" }, [
      el("div", { class: "listing__title" }, [displayTitle(l), " ", ...badges]),
      el("div", { class: "listing__price", text: fmtPrice(l.price, l.currency, l.extra_costs) }),
    ]),
    metaLine(l) ? el("div", { class: "listing__meta", text: metaLine(l) }) : null,
    fmtWhen(l.first_seen_utc) ? el("div", { class: "listing__when", text: fmtWhen(l.first_seen_utc) }) : null,
    alsoOn,
    actions,
  ]);

  node.appendChild(body);
  node.appendChild(star);
  return node;
}

function markSeen(l) {
  setSeen(l.uid, true);
  setTimeout(render, 60);
}

// --- порожні стани -------------------------------------------------

function emptyState(iconName, title, text, withSuggestions) {
  const box = el("div", { class: "empty" }, [
    el("div", { class: "empty__icon" }, [icon(iconName, { size: 30, stroke: 1.8 })]),
    el("div", { class: "empty__title", text: title }),
    el("p", { class: "empty__text", text: text }),
  ]);
  if (withSuggestions) {
    box.appendChild(el("div", { class: "chips" }, SUGGESTIONS.map((s) =>
      el("button", { class: "chip", text: s, onclick: () => runSearch(s) }))));
    box.appendChild(el("div", { class: "steps" }, [
      "Пишеш у пошук, що шукаєш — місто, ціну, кількість спалень",
      "AI перевіряє Immoweb і Immovlan та одразу показує знайдене",
      "Результати з'являються тут же — фото, ціна, посилання",
    ].map((t, i) => el("div", { class: "step" }, [
      el("div", { class: "step__n", text: String(i + 1) }),
      el("div", { class: "step__t", text: t }),
    ]))));
  }
  return box;
}

// --- рендер --------------------------------------------------------

export function renderBoard(root, opts = {}) {
  rootEl = root;
  clear(root);
  mode = opts.mode === "favorites" ? "favorites" : baseMode();

  if (mode === "favorites") {
    root.appendChild(el("div", { class: "page-head" }, [
      el("a", { class: "back-link", href: "#/" }, [icon("chevron", { size: 16, stroke: 2.4 }), " На головну"]),
      el("h1", { class: "page-title", text: "Обране" }),
      el("p", { class: "muted", text: "Оголошення, які ти позначив зіркою. Синхронізуються між пристроями." }),
    ]));
  } else {
    root.appendChild(el("section", { class: "search" }, [
    el("h1", { class: "search__title", text: "Знайди квартиру в Бельгії за секунди" }),
    el("p", { class: "search__subtitle", text:
      "Напиши, що шукаєш — AI перевірить Immoweb і Immovlan та покаже результати одразу." }),
    (() => {
      const input = el("input", {
        class: "search__input", id: "chatInput", type: "text", autocomplete: "off",
        placeholder: "напр. квартира в Антверпені до 700€, за останні 2 дні",
      });
      const field = el("div", { class: "search__field" }, [
        icon("search", { size: 19, stroke: 2.2 }),
        input,
      ]);
      const form = el("form", { class: "search__bar", onsubmit: (e) => {
        e.preventDefault();
        const t = input.value.trim();
        if (t) { input.value = ""; runSearch(t); }
      } }, [
        field,
        el("button", { class: "btn btn-primary search__submit", type: "submit" }, [
          icon("search", { size: 18, stroke: 2.4 }), " Шукати",
        ]),
      ]);
      return form;
    })(),
    el("div", { class: "search__reply", id: "chatReply", hidden: "" }),
    ]));
  }

  root.appendChild(el("div", { class: "board-bar", id: "boardBar", hidden: "" }, [
    el("span", { class: "board-bar__count", id: "boardCount" }),
    el("div", { class: "board-bar__actions" }, [
      el("button", { class: "btn btn-sm" + (onlyUnseen ? " is-on" : ""), id: "unseenBtn",
        text: onlyUnseen ? "Показано: тільки нові" : "Тільки непереглянуті",
        onclick: () => { onlyUnseen = !onlyUnseen; render(); } }),
      el("button", { class: "btn btn-sm", text: "Позначити всі переглянутими", onclick: markAll }),
      (() => {
        const sel = el("select", { class: "select select--sm", onchange: (e) => { sortBy = e.target.value; render(); } }, [
          el("option", { value: "date", text: "Спочатку нові" }),
          el("option", { value: "price_asc", text: "Дешевші спочатку" }),
          el("option", { value: "price_desc", text: "Дорожчі спочатку" }),
        ]);
        sel.value = sortBy;
        return sel;
      })(),
    ]),
  ]));

  root.appendChild(el("div", { id: "boardList", class: "board-list" }));
  render();
}

function render() {
  if (!rootEl || !rootEl.isConnected) return;
  const list = rootEl.querySelector("#boardList");
  const bar = rootEl.querySelector("#boardBar");
  const count = rootEl.querySelector("#boardCount");
  if (!list) return;
  clear(list);

  const base = currentBase();
  let items = base.filter((l) => (onlyUnseen ? !isSeen(l.uid) : true));
  items = sortItems(items);

  bar.hidden = mode === "home";
  if (mode === "favorites") {
    count.textContent = "В обраному: " + base.length;
  } else {
    const unseen = base.filter((l) => !isSeen(l.uid)).length;
    count.textContent = base.length + " оголошень, непереглянутих: " + unseen;
  }

  if (items.length) {
    items.forEach((l) => list.appendChild(card(l)));
    return;
  }
  if (mode === "favorites") {
    list.appendChild(emptyState("star", "В обраному порожньо",
      "Натисни зірку на будь-якій картці — і оголошення з'явиться тут.", false));
  } else if (mode === "since") {
    list.appendChild(emptyState("inbox", "Нічого нового",
      "Із цього листа нових оголошень не лишилось.", false));
  } else if (mode === "search") {
    list.appendChild(emptyState("search", "Нічого не знайдено",
      "Спробуй змінити запит — інше місто, вищу ціну або менше кімнат.", false));
  } else {
    list.appendChild(emptyState("home", "Почни з пошуку",
      "Напиши запит угорі — AI перевірить Immoweb і Immovlan.", true));
  }
}

function markAll() {
  if (!confirm("Позначити всі оголошення як переглянуті?")) return;
  const m = readMap(SEEN_KEY);
  currentBase().forEach((l) => { if (!m[l.uid]) m[l.uid] = new Date().toISOString(); });
  writeMap(SEEN_KEY, m);
  scheduleSync("seen");
  render();
}

// --- AI-пошук -----------------------------------------------------

function showReply(text, isError) {
  const box = rootEl?.querySelector("#chatReply");
  if (!box) return;
  box.textContent = text || "";
  box.hidden = !text;
  box.classList.toggle("search__reply--error", !!isError);
}

function runSearch(text) {
  const input = rootEl?.querySelector("#chatInput");
  if (input) input.value = "";
  showReply("Шукаю…");
  chatSearch(text, chatHistory)
    .then((data) => {
      const reply = data.reply || "…";
      showReply(reply);
      chatHistory.push({ role: "user", content: text });
      chatHistory.push({ role: "assistant", content: reply });
      mode = "search";
      searchResults = data.listings || [];
      render();
    })
    .catch((err) => {
      if (err.code === "unauthorized") { showReply("Сесія завершилась — увійди ще раз.", true); toast("Увійди ще раз", "error"); return; }
      if (err.code === "no_subscription") { showReply("Для AI-пошуку потрібна активна підписка.", true); location.hash = "#/subscription"; return; }
      showReply(err.message, true);
    });
}
