/*
 * main.js — збирає все докупи:
 *   • готує вхід через Google;
 *   • після входу питає сервер «що мені дозволено» (/api/me);
 *   • показує потрібний екран: лендінг → підписка неактивна → сайт;
 *   • простий роутер за адресним «хешем»: #/ , #/profile , #/admin.
 */

import { fetchMe, loadSession } from "./api.js";
import { initAuth, onAuthChange, signIn, signOut } from "./auth.js";
import { el, clear, rawSvg, revealOnScroll } from "./ui.js";
import { loadData, renderBoard, syncFromServer, resetToBase } from "./board.js";
import { renderProfile, renderLocked, refreshFeedBadge, feedUnread } from "./profile.js";
import { renderAdmin } from "./admin.js";

const app = document.getElementById("app");
const nav = document.getElementById("nav");

let entitlement = null; // { active, is_admin, status, plan, expires_utc }
let me = null;

// --- завантаження (сам запуск — у кінці файлу, коли все оголошено) ---

function boot() {
  const session = loadSession();
  if (!session) {
    entitlement = null; me = null;
    paintNav();
    renderLanding();
    return;
  }
  fetchMe()
    .then((data) => {
      me = data.user;
      entitlement = data.entitlement;
      paintNav();
      if (entitlement.active) {
        loadData().then(() => { syncFromServer(); route(); });
        refreshFeedBadge().then(paintNav);
      } else {
        route();
      }
    })
    .catch((err) => {
      if (err.code === "unauthorized") { signOut(); return; }
      entitlement = null;
      paintNav();
      renderLanding("Сервер зараз недоступний. Онови сторінку за хвилину.");
    });
}

// --- логотип ------------------------------------------------------

const LOGO_SVG = `
<svg class="brand__logo" viewBox="0 0 36 36" width="36" height="36" aria-hidden="true">
  <defs>
    <linearGradient id="reabLogo" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#33e9ea"/>
      <stop offset="1" stop-color="#1170d8"/>
    </linearGradient>
  </defs>
  <rect x="1.5" y="1.5" width="33" height="33" rx="10.5" fill="url(#reabLogo)"/>
  <path class="brand__roof" d="M8.5 18.5 18 10l9.5 8.5" fill="none" stroke="#fff"
        stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M11 17.2V26h14v-8.8" fill="none" stroke="#fff"
        stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
  <circle class="brand__spark" cx="27.5" cy="8.5" r="3" fill="#fff"/>
</svg>`;

function brandNode() {
  return el("a", { class: "brand", href: "#/" }, [
    rawSvg(LOGO_SVG),
    el("span", { class: "brand__name" }, [
      el("span", { class: "brand__kw", text: "Kwartira" }),
      el("span", { class: "brand__be", text: "BE" }),
    ]),
  ]);
}

// --- навігація -----------------------------------------------------

function paintNav() {
  clear(nav);
  nav.appendChild(brandNode());

  const session = loadSession();
  if (!session) {
    nav.appendChild(el("button", { class: "btn btn-primary btn-sm nav__cta", text: "Увійти через Google", onclick: signIn }));
    return;
  }

  const links = el("div", { class: "nav__links" });
  if (entitlement && entitlement.active) {
    links.appendChild(navLink("#/", "Дошка"));
    const badge = feedUnread() > 0 ? el("span", { class: "nav__badge", text: String(feedUnread()) }) : null;
    links.appendChild(navLink("#/profile", "Кабінет", badge));
    if (entitlement.is_admin) links.appendChild(navLink("#/admin", "Адмін"));
  }
  nav.appendChild(links);

  const chip = el("div", { class: "user-chip" }, [
    session.picture ? el("img", { src: session.picture, alt: "", referrerpolicy: "no-referrer" }) : null,
    el("span", { text: session.name || session.email }),
  ]);
  nav.appendChild(el("div", { class: "nav__right" }, [
    chip,
    el("button", { class: "btn btn-ghost btn-sm", text: "Вийти", onclick: signOut }),
  ]));
}

function navLink(hash, text, extra) {
  const active = (location.hash || "#/") === hash;
  return el("a", { class: "nav__link" + (active ? " is-active" : ""), href: hash }, [text, extra]);
}

// --- роутер -------------------------------------------------------

function playEnter() {
  app.classList.remove("view-enter");
  void app.offsetWidth; // перезапуск анімації
  app.classList.add("view-enter");
}

function route() {
  const session = loadSession();
  if (!session) { renderLanding(); return; }
  if (!entitlement) { renderLanding(); return; }
  if (!entitlement.active) { renderLocked(app, entitlement); paintNav(); playEnter(); return; }

  const hash = location.hash || "#/";
  paintNav();
  if (hash.startsWith("#/profile")) {
    renderProfile(app, entitlement);
    refreshFeedBadge().then(paintNav);
  } else if (hash.startsWith("#/admin") && entitlement.is_admin) {
    renderAdmin(app);
  } else {
    resetToBase();
    renderBoard(app);
  }
  playEnter();
  revealOnScroll(app);
  window.scrollTo(0, 0);
}

// --- публічний лендінг -------------------------------------------

function renderLanding(notice) {
  clear(app);

  const features = [
    ["🤖", "AI-пошук", "Пишеш звичайною мовою — «квартира в Генті до 800€» — а система перекладає це в критерії й одразу шукає по двох сайтах."],
    ["✉️", "Розсилка + стрічка", "Нові оголошення за твоїми критеріями приходять на пошту й у стрічку кабінету з обраним інтервалом."],
    ["⚡", "Оптика Proximus", "Для кожної адреси перевіряється, чи є там оптоволокно — видно прямо на картці оголошення."],
    ["📍", "Точна адреса", "Кнопка «На карті» веде в Google Maps на конкретний будинок, а не на центр міста."],
    ["⭐", "Обране й «переглянуто»", "Позначки синхронізуються між телефоном і комп'ютером — нічого не губиться."],
    ["🔒", "Приватний доступ", "Вхід через Google + підписка. Тільки ти вирішуєш, кому відкрити сайт."],
  ];
  const stats = [
    ["2", "сайти в одному пошуку"],
    ["1 год", "мінімальний інтервал розсилки"],
    ["90 днів", "історія оголошень на дошці"],
    ["0 €", "хостинг (GitHub + Render)"],
  ];
  const steps = [
    "Увійди через Google — це замінює будь-які коди доступу",
    "Опиши в пошуку, що шукаєш — місто, ціну, кімнати",
    "Отримуй нові квартири в стрічці кабінету й на пошті",
  ];
  const stack = ["Python", "Flask", "GitHub Actions", "SQLite", "Vanilla JS", "Google Sign-In", "Render"];

  // герой
  app.appendChild(el("section", { class: "hero reveal" }, [
    el("div", { class: "hero__blob hero__blob--1" }),
    el("div", { class: "hero__blob hero__blob--2" }),
    el("div", { class: "hero__inner" }, [
      notice ? el("div", { class: "hero__notice", text: notice }) : null,
      el("div", { class: "hero__badge", text: "Агрегатор нерухомості · Бельгія" }),
      el("h1", { class: "hero__title" }, [
        "Усі нові квартири ",
        el("span", { class: "grad-text", text: "Immoweb та Immovlan" }),
        " — в одному місці",
      ]),
      el("p", { class: "hero__subtitle", text:
        "AI-пошук, розсилка на пошту й особистий кабінет зі стрічкою нових оголошень. Увійди через Google, щоб почати." }),
      el("div", { class: "hero__cta" }, [
        el("button", { class: "btn btn-primary btn-lg btn-shine", text: "Увійти через Google", onclick: signIn }),
      ]),
      el("p", { class: "hero__hint", text: "Доступ до сайту — за підпискою, яку вмикає власник." }),
    ]),
  ]));

  // числа
  app.appendChild(el("section", { class: "stats reveal" }, stats.map(([n, label]) =>
    el("div", { class: "stat" }, [
      el("div", { class: "stat__n", text: n }),
      el("div", { class: "stat__label", text: label }),
    ]))));

  // можливості
  app.appendChild(el("section", { class: "block reveal" }, [
    el("div", { class: "section-eyebrow", text: "Що вміє" }),
    el("h2", { class: "section-title", text: "Усе для щоденного пошуку житла" }),
    el("div", { class: "features" }, features.map(([icon, title, text], i) =>
      el("div", { class: "feature", style: `--d:${i * 60}ms` }, [
        el("div", { class: "feature__icon", text: icon }),
        el("h3", { class: "feature__title", text: title }),
        el("p", { class: "feature__text", text: text }),
      ]))),
  ]));

  // як це працює
  app.appendChild(el("section", { class: "block reveal" }, [
    el("div", { class: "section-eyebrow", text: "Як це працює" }),
    el("h2", { class: "section-title", text: "Три кроки" }),
    el("div", { class: "steps steps--lg" }, steps.map((t, i) =>
      el("div", { class: "step" }, [
        el("div", { class: "step__n", text: String(i + 1) }),
        el("div", { class: "step__t", text: t }),
      ]))),
  ]));

  // стек
  app.appendChild(el("section", { class: "stack reveal" }, [
    el("span", { class: "stack__label", text: "Зроблено на" }),
    ...stack.map((s) => el("span", { class: "stack__item", text: s })),
  ]));

  // фінальний заклик
  app.appendChild(el("section", { class: "cta-band reveal" }, [
    el("h2", { class: "cta-band__title", text: "Готовий подивитись, що на ринку?" }),
    el("button", { class: "btn btn-primary btn-lg btn-shine", text: "Увійти через Google", onclick: signIn }),
  ]));

  app.appendChild(el("footer", { class: "site-footer", text:
    "Пет-проєкт для портфоліо · дані беруться з публічних оголошень Immoweb і Immovlan" }));

  playEnter();
  revealOnScroll(app);
}

// --- запуск --------------------------------------------------------

initAuth();
onAuthChange(() => boot());
window.addEventListener("hashchange", route);
window.addEventListener("reab:feed", () => paintNav());
boot();
