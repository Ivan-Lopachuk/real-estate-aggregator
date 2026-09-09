/*
 * ui.js — дрібні спільні помічники: створення елементів і форматування
 * тексту оголошень. Жодної бізнес-логіки, лише «як показати».
 */

/** Коротке створення елемента: el("div", {class: "card"}, [child1, "текст"]). */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function show(node, visible = true) {
  if (node) node.hidden = !visible;
}

// --- форматування -----------------------------------------------------

export function fmtPrice(p, cur, extraCosts) {
  if (p == null) return "ціна не вказана";
  const unit = cur === "EUR" ? "€" : (cur || "");
  let s = Math.round(p).toLocaleString("uk-UA").replace(/,/g, " ") + " " + unit;
  if (extraCosts) {
    s += " (+" + Math.round(extraCosts).toLocaleString("uk-UA").replace(/,/g, " ") + " " + unit + ")";
  }
  return s.trim();
}

export function fmtWhen(iso) {
  // Без дати не показуємо нічого (new Date(null) дало б 1970 рік).
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days <= 0) return "побачено сьогодні";
  if (days === 1) return "побачено вчора";
  return "побачено " + days + " дн. тому";
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleDateString("uk-UA", { day: "numeric", month: "long", year: "numeric" });
}

export function siteLabel(url) {
  if (!url) return "сайті";
  if (url.indexOf("immoweb.be") !== -1) return "Immoweb";
  if (url.indexOf("immovlan.be") !== -1) return "Immovlan";
  return "сайті";
}

/**
 * Назва картки. Якщо сайт не дав кількості спалень — прибираємо
 * «· N спалень», якщо воно якось потрапило в назву (старі записи).
 */
export function displayTitle(l) {
  let t = l.title || "Оголошення";
  if (!l.bedrooms) {
    t = t.replace(/\s*·\s*\d+\s+спальн\S*/i, "")
         .replace(/^\s*\d+\s+спальн\S*\s*·\s*/i, "")
         .trim();
  }
  return t || "Оголошення";
}

export function metaLine(l) {
  const bits = [];
  if (l.bedrooms) bits.push(l.bedrooms + " спалень"); // 0/відсутнє — не пишемо «0 спалень»
  if (l.living_area) bits.push(Math.round(l.living_area) + " м²");
  const addr = [l.street, l.house_number].filter(Boolean).join(" ");
  const place = [l.postal_code, l.locality].filter(Boolean).join(" ");
  const full = [addr, place].filter(Boolean).join(", ");
  if (full) bits.push(full);
  return bits.join(" · ");
}

/**
 * Посилання «📍 На карті» — Google Maps на точну адресу квартири
 * (вулиця + номер, як у ~95% Immoweb); якщо адреси немає — на місто за
 * індексом. null, якщо немає ні адреси, ні міста (кнопку не показуємо).
 */
export function buildMapLink(l) {
  const street = [l.street, l.house_number].filter(Boolean).join(" ");
  const place = [l.postal_code, l.locality].filter(Boolean).join(" ");
  const parts = [street, place].filter(Boolean);
  if (!parts.length) return null;
  parts.push("Belgium");
  return el("a", {
    class: "btn btn-ghost btn-sm",
    href: "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(parts.join(", ")),
    target: "_blank",
    rel: "noopener",
    text: street ? "📍 На карті" : "📍 Місто на карті",
    title: street
      ? "Показати точну адресу в Google Maps"
      : "Точної адреси в оголошенні немає — показати місто",
  });
}

/** Невеликий тост унизу екрана. */
export function toast(message, kind = "ok") {
  let host = document.getElementById("toastHost");
  if (!host) {
    host = el("div", { id: "toastHost", class: "toast-host" });
    document.body.appendChild(host);
  }
  const t = el("div", { class: `toast toast-${kind}`, text: message });
  host.appendChild(t);
  setTimeout(() => t.classList.add("in"), 10);
  setTimeout(() => { t.classList.remove("in"); setTimeout(() => t.remove(), 300); }, 3600);
}
