/*
 * profile.js — кабінет користувача:
 *   1) картка підписки (план, статус, коли закінчується);
 *   2) розсилка — критерії, за якими на пошту приходять нові квартири;
 *   3) стрічка сповіщень — ті самі квартири, але переглядати їх можна тут.
 */

import {
  getSubscription, saveSubscription, cancelSubscription,
  getFeed, markFeedRead, requestAccess,
} from "./api.js";
import { el, clear, fmtPrice, fmtWhen, fmtDate, siteLabel, displayTitle, toast } from "./ui.js";

let unread = 0;
export function feedUnread() { return unread; }

/** Оновлює лічильник непрочитаних (для значка в навігації). Повертає число. */
export function refreshFeedBadge() {
  return getFeed().then((d) => { unread = d.unread || 0; return unread; }).catch(() => unread);
}

// --- підписка неактивна: екран «Попросити доступ» -------------------

export function renderLocked(root, entitlement) {
  clear(root);
  const box = el("div", { class: "panel panel--narrow center" }, [
    el("div", { class: "lock-icon", text: "🔒" }),
    el("h1", { class: "panel__title", text: "Підписка неактивна" }),
    el("p", { class: "muted", text:
      entitlement.status === "active"
        ? "Термін твоєї підписки завершився. Попроси власника продовжити доступ."
        : "Цей сайт працює за підпискою. Доступ вмикає власник вручну — залиш прохання нижче." }),
    el("label", { class: "field" }, [
      el("span", { text: "Коротке повідомлення (необов'язково)" }),
      el("textarea", { id: "accessMsg", rows: "3", placeholder: "напр. шукаю квартиру в Генті, хочу користуватись пошуком" }),
    ]),
    el("button", { class: "btn btn-primary", text: "Надіслати прохання", onclick: (e) => {
      const btn = e.target;
      btn.disabled = true;
      requestAccess(document.getElementById("accessMsg").value.trim())
        .then(() => toast("Прохання надіслано власнику", "ok"))
        .catch((err) => toast(err.message, "error"))
        .finally(() => { btn.disabled = false; });
    } }),
  ]);
  root.appendChild(box);
}

// --- кабінет -------------------------------------------------------

export function renderProfile(root, entitlement) {
  clear(root);
  root.appendChild(el("h1", { class: "page-title", text: "Кабінет" }));
  root.appendChild(subscriptionCard(entitlement));

  const subPanel = el("section", { class: "panel", id: "subPanel" });
  root.appendChild(subPanel);
  renderSubscriptionForm(subPanel);

  const feedPanel = el("section", { class: "panel", id: "feedPanel" }, [
    el("div", { class: "panel__head" }, [
      el("h2", { class: "panel__title", text: "Стрічка нових квартир" }),
      el("button", { class: "btn btn-sm", id: "feedReadAll", text: "Позначити всі прочитаними",
        onclick: () => markFeedRead({ all: true }).then(() => loadFeed(feedPanel)).catch(() => {}) }),
    ]),
    el("p", { class: "muted", text:
      "Те саме, що приходить тобі на пошту з розсилки — щоб не перевіряти пошту." }),
    el("div", { class: "feed", id: "feedList" }),
  ]);
  root.appendChild(feedPanel);
  loadFeed(feedPanel);
}

function subscriptionCard(e) {
  const status = e.is_admin
    ? "Адміністратор — повний доступ"
    : e.active ? "Активна" : (e.status === "active" ? "Термін завершився" : "Неактивна");
  const rows = [
    ["Статус", status],
    ["План", e.plan || "—"],
  ];
  if (e.expires_utc) rows.push(["Діє до", fmtDate(e.expires_utc)]);
  return el("section", { class: "panel sub-card" }, [
    el("div", { class: "panel__head" }, [
      el("h2", { class: "panel__title", text: "Моя підписка" }),
      el("span", { class: "pill " + (e.active ? "pill--ok" : "pill--off"), text: e.active ? "активна" : "неактивна" }),
    ]),
    el("dl", { class: "kv" }, rows.flatMap(([k, v]) => [
      el("dt", { text: k }), el("dd", { text: v }),
    ])),
  ]);
}

// --- форма розсилки ---------------------------------------------

function field(labelText, control) {
  return el("label", { class: "field" }, [el("span", { text: labelText }), control]);
}

function renderSubscriptionForm(panel) {
  clear(panel);
  panel.appendChild(el("div", { class: "panel__head" }, [
    el("h2", { class: "panel__title", text: "Розсилка на пошту" }),
  ]));
  panel.appendChild(el("p", { class: "muted", text:
    "Нові оголошення за цими критеріями приходитимуть на вказану пошту з обраним інтервалом (і сюди, у стрічку)." }));

  const f = {
    place: el("input", { type: "text", placeholder: "напр. Antwerpen" }),
    transaction: el("select", {}, [el("option", { value: "rent", text: "Оренда" }), el("option", { value: "sale", text: "Купівля" })]),
    interval: el("select", {}, [
      ["1", "Щогодини"], ["3", "Кожні 3 год"], ["6", "Кожні 6 год"],
      ["12", "Кожні 12 год"], ["24", "Раз на добу"], ["168", "Раз на тиждень"],
    ].map(([v, t]) => el("option", { value: v, text: t }))),
    house: el("input", { type: "checkbox", checked: "" }),
    apartment: el("input", { type: "checkbox", checked: "" }),
    priceMin: el("input", { type: "number", min: "1", step: "1" }),
    priceMax: el("input", { type: "number", min: "1", step: "1" }),
    bedroomsMin: el("input", { type: "number", min: "1", step: "1" }),
    bedroomsMax: el("input", { type: "number", min: "1", step: "1" }),
    areaMin: el("input", { type: "number", min: "1", step: "1" }),
    email: el("input", { type: "email", placeholder: "твоя@пошта.com" }),
  };

  const status = el("div", { class: "form-status", hidden: "" });
  const cancelBtn = el("button", { class: "btn btn-danger", text: "Скасувати розсилку", hidden: "",
    onclick: () => {
      if (!confirm("Скасувати розсилку?")) return;
      cancelSubscription().then(() => { fill(null); setStatus("Розсилку скасовано."); }).catch((e) => setStatus(e.message, true));
    } });

  panel.appendChild(el("div", { class: "form-grid" }, [
    field("Місто чи район", f.place),
    el("div", { class: "form-row" }, [field("Тип угоди", f.transaction), field("Інтервал листів", f.interval)]),
    el("div", { class: "checks" }, [
      el("label", { class: "check" }, [f.house, " Будинок"]),
      el("label", { class: "check" }, [f.apartment, " Квартира"]),
    ]),
    el("div", { class: "form-row" }, [field("Ціна від, €", f.priceMin), field("Ціна до, €", f.priceMax)]),
    el("div", { class: "form-row" }, [field("Спалень від", f.bedroomsMin), field("Спалень до", f.bedroomsMax)]),
    field("Площа від, м²", f.areaMin),
    field("Пошта для листів", f.email),
    status,
    el("div", { class: "form-actions" }, [
      el("button", { class: "btn btn-primary", text: "Зберегти розсилку", onclick: submit }),
      cancelBtn,
    ]),
  ]));

  function setStatus(text, isError) {
    status.hidden = !text;
    status.textContent = text || "";
    status.className = "form-status " + (isError ? "form-status--error" : "form-status--ok");
  }

  function fill(sub) {
    const s = (sub && sub.search) || {};
    f.place.value = sub ? (sub.place || "") : "";
    f.transaction.value = s.transaction || "rent";
    const types = s.property_types || ["house", "apartment"];
    f.house.checked = types.includes("house");
    f.apartment.checked = types.includes("apartment");
    f.priceMin.value = s.price_min ?? "";
    f.priceMax.value = s.price_max ?? "";
    f.bedroomsMin.value = s.bedrooms_min ?? "";
    f.bedroomsMax.value = s.bedrooms_max ?? "";
    f.areaMin.value = s.living_area_min ?? "";
    f.interval.value = sub ? String(sub.interval_hours) : "6";
    const session = JSON.parse(localStorage.getItem("reab:google-user") || "null");
    f.email.value = sub ? (sub.notify_email || "") : (session ? session.email : "");
    cancelBtn.hidden = !sub;
  }

  function submit() {
    const body = {
      place: f.place.value.trim(),
      transaction: f.transaction.value,
      property_types: [f.house.checked && "house", f.apartment.checked && "apartment"].filter(Boolean),
      price_min: f.priceMin.value || null,
      price_max: f.priceMax.value || null,
      bedrooms_min: f.bedroomsMin.value || null,
      bedrooms_max: f.bedroomsMax.value || null,
      living_area_min: f.areaMin.value || null,
      interval_hours: f.interval.value,
      notify_email: f.email.value.trim(),
    };
    setStatus("Зберігаю…");
    saveSubscription(body)
      .then((res) => { fill(res.subscription); setStatus("Збережено! Перший лист прийде за кілька хвилин."); })
      .catch((e) => setStatus(e.message, true));
  }

  fill(null);
  getSubscription().then((d) => { if (d.subscription) fill(d.subscription); }).catch(() => {});
}

// --- стрічка -----------------------------------------------------

function loadFeed(panel) {
  const list = panel.querySelector("#feedList");
  clear(list);
  list.appendChild(el("p", { class: "muted", text: "Завантажую…" }));
  getFeed().then((d) => {
    unread = d.unread || 0;
    window.dispatchEvent(new CustomEvent("reab:feed", { detail: unread }));
    clear(list);
    const items = d.items || [];
    panel.querySelector("#feedReadAll").hidden = !unread;
    if (!items.length) {
      list.appendChild(el("div", { class: "empty" }, [
        el("div", { class: "empty__icon", text: "📭" }),
        el("div", { class: "empty__title", text: "Стрічка порожня" }),
        el("p", { class: "empty__text", text: "Створи розсилку вище — і нові квартири з'являтимуться тут." }),
      ]));
      return;
    }
    items.forEach((it) => list.appendChild(feedItem(it, panel)));
  }).catch((err) => {
    clear(list);
    list.appendChild(el("p", { class: "form-status form-status--error", text: err.message }));
  });
}

function feedItem(it, panel) {
  const node = el("a", {
    class: "feed-item" + (it.read ? " feed-item--read" : ""),
    href: it.url, target: "_blank", rel: "noopener",
    onclick: () => {
      if (!it.read) markFeedRead({ uids: [it.uid] }).then(() => loadFeed(panel)).catch(() => {});
    },
  }, [
    it.photo_url ? el("img", { class: "feed-item__photo", src: it.photo_url, alt: "", loading: "lazy" }) : null,
    el("div", { class: "feed-item__body" }, [
      el("div", { class: "feed-item__title", text: displayTitle(it) }),
      el("div", { class: "feed-item__meta", text:
        [fmtPrice(it.price, it.currency), [it.postal_code, it.locality].filter(Boolean).join(" ")].filter(Boolean).join(" · ") }),
      el("div", { class: "feed-item__when", text:
        (fmtWhen(it.sent_utc) || "") + " · " + siteLabel(it.url) }),
    ]),
    it.read ? null : el("span", { class: "feed-item__dot", title: "не прочитано" }),
  ]);
  return node;
}
