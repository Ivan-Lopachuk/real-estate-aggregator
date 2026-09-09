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

/** Створює вузол зі шматка розмітки (напр. вбудований <svg>). */
export function rawSvg(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstChild;
}

// Набір акуратних лінійних іконок (24×24, колір успадковується через
// currentColor). Замість «примітивних» емодзі на кнопках і в підказках.
const ICON_PATHS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
  home: '<path d="M3 10.7 12 3.5l9 7.2"/><path d="M5.2 9.4V20a1 1 0 0 0 1 1h11.6a1 1 0 0 0 1-1V9.4"/><path d="M9.7 21v-5.2a1 1 0 0 1 1-1h2.6a1 1 0 0 1 1 1V21"/>',
  star: '<path d="M12 3.5l2.6 5.3 5.9.86-4.25 4.14 1 5.87L12 17.9l-5.25 2.76 1-5.87L3.5 9.66l5.9-.86z"/>',
  inbox: '<path d="M3 13h4l1.5 3h7L17 13h4"/><path d="M4.2 13 6 5.4a2 2 0 0 1 1.95-1.5h8.1A2 2 0 0 1 18 5.4L19.8 13v4.6a2 2 0 0 1-2 2H6.2a2 2 0 0 1-2-2z"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.6 2.2a.6.6 0 0 1-.5 1H4.9a.6.6 0 0 1-.5-1z"/><path d="M9.5 20.5a2.5 2.5 0 0 0 5 0"/>',
  lock: '<rect x="4.5" y="10.5" width="15" height="10.5" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
};

/** SVG-іконка з набору. opts: { size, stroke } */
export function icon(name, { size = 20, stroke = 2 } = {}) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", stroke);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  svg.innerHTML = ICON_PATHS[name] || "";
  return svg;
}

/**
 * Додає клас .in елементам .reveal, коли вони з'являються у вікні —
 * для плавної появи секцій при прокручуванні.
 */
export function revealOnScroll(root) {
  if (!("IntersectionObserver" in window)) {
    root.querySelectorAll(".reveal").forEach((n) => n.classList.add("in"));
    return;
  }
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  root.querySelectorAll(".reveal").forEach((n) => io.observe(n));
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
