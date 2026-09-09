/*
 * main.js — збирає все докупи:
 *   • готує вхід через Google;
 *   • після входу питає сервер «що мені дозволено» (/api/me);
 *   • показує потрібний екран: лендінг → підписка неактивна → сайт;
 *   • простий роутер за адресним «хешем»: #/ , #/profile , #/admin.
 */

import { fetchMe, loadSession } from "./api.js";
import { initAuth, onAuthChange, signIn, signOut, currentUser } from "./auth.js";
import { el, clear, show } from "./ui.js";
import { loadData, renderBoard, syncFromServer, resetToBase } from "./board.js";
import { renderProfile, renderLocked, refreshFeedBadge, feedUnread } from "./profile.js";
import { renderAdmin } from "./admin.js";

const app = document.getElementById("app");
const nav = document.getElementById("nav");

let entitlement = null; // { active, is_admin, status, plan, expires_utc }
let me = null;

// --- завантаження ---------------------------------------------------

initAuth();
onAuthChange(() => boot());
window.addEventListener("hashchange", route);
window.addEventListener("reab:feed", () => paintNav());
boot();

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
      // сервер спить / немає мережі — показуємо лендінг із поясненням
      entitlement = null;
      paintNav();
      renderLanding("Сервер зараз недоступний. Онови сторінку за хвилину.");
    });
}

// --- навігація -----------------------------------------------------

function paintNav() {
  clear(nav);
  const brand = el("a", { class: "brand", href: "#/", text: "🏡 KwartiraBE" });
  nav.appendChild(brand);

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

function route() {
  const session = loadSession();
  if (!session) { renderLanding(); return; }
  if (!entitlement) { renderLanding(); return; }
  if (!entitlement.active) { renderLocked(app, entitlement); paintNav(); return; }

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
  window.scrollTo(0, 0);
}

// --- публічний лендінг -------------------------------------------

function renderLanding(notice) {
  clear(app);
  const features = [
    ["🤖", "AI-пошук", "Пишеш звичайною мовою — «квартира в Генті до 800€» — а система перекладає це в критерії й одразу шукає."],
    ["✉️", "Розсилка", "Нові оголошення за твоїми критеріями приходять на пошту й у стрічку кабінету з обраним інтервалом."],
    ["⚡", "Оптика Proximus", "Для кожної адреси перевіряється, чи є там оптоволокно — видно прямо на картці."],
    ["📍", "Точна адреса", "Кнопка «На карті» веде в Google Maps на конкретний будинок, а не на центр міста."],
  ];
  const stack = ["Python", "Flask", "GitHub Actions", "SQLite", "Vanilla JS", "Google Sign-In"];

  app.appendChild(el("section", { class: "hero" }, [
    notice ? el("div", { class: "hero__notice", text: notice }) : null,
    el("div", { class: "hero__badge", text: "Агрегатор нерухомості · Бельгія" }),
    el("h1", { class: "hero__title", text: "Усі нові квартири Immoweb та Immovlan — в одному місці" }),
    el("p", { class: "hero__subtitle", text:
      "AI-пошук, розсилка на пошту й особистий кабінет зі стрічкою нових оголошень. Увійди через Google, щоб почати." }),
    el("button", { class: "btn btn-primary btn-lg", text: "Увійти через Google", onclick: signIn }),
    el("p", { class: "hero__hint", text: "Доступ до сайту — за підпискою, яку вмикає власник." }),
  ]));

  app.appendChild(el("section", { class: "features" }, features.map(([icon, title, text]) =>
    el("div", { class: "feature" }, [
      el("div", { class: "feature__icon", text: icon }),
      el("h3", { class: "feature__title", text: title }),
      el("p", { class: "feature__text", text: text }),
    ]))));

  app.appendChild(el("section", { class: "stack" }, [
    el("span", { class: "stack__label", text: "Зроблено на" }),
    ...stack.map((s) => el("span", { class: "stack__item", text: s })),
  ]));

  app.appendChild(el("footer", { class: "site-footer", text:
    "Пет-проєкт для портфоліо · дані беруться з публічних оголошень Immoweb і Immovlan" }));
}
