/*
 * admin.js — панель адміністратора (лише для пошт зі списку ADMIN_EMAILS
 * на сервері). Тут власник вмикає й вимикає підписку іншим людям за їхньою
 * поштою та бачить, хто просив доступ.
 */

import {
  adminListSubscriptions, adminGrantSubscription, adminRevokeSubscription,
  adminListAccessRequests,
} from "./api.js";
import { el, clear, fmtDate, toast } from "./ui.js";

export function renderAdmin(root) {
  clear(root);
  root.appendChild(el("h1", { class: "page-title", text: "Панель адміністратора" }));

  const grant = el("section", { class: "panel" }, [
    el("h2", { class: "panel__title", text: "Видати або продовжити підписку" }),
    el("p", { class: "muted", text: "Впиши пошту акаунта Google людини. Дата закінчення — необов'язкова (порожня = безстроково)." }),
    (() => {
      const email = el("input", { type: "email", placeholder: "person@gmail.com" });
      const until = el("input", { type: "date" });
      const note = el("input", { type: "text", placeholder: "нотатка (необов'язково)" });
      const form = el("form", { class: "form-grid", onsubmit: (ev) => {
        ev.preventDefault();
        const body = { email: email.value.trim() };
        if (until.value) body.expires_utc = until.value + "T23:59:59+00:00";
        if (note.value.trim()) body.note = note.value.trim();
        adminGrantSubscription(body)
          .then((d) => { toast("Підписку збережено", "ok"); email.value = ""; until.value = ""; note.value = ""; fillTable(d.subscriptions); })
          .catch((err) => toast(err.message, "error"));
      } }, [
        el("label", { class: "field" }, [el("span", { text: "Пошта" }), email]),
        el("div", { class: "form-row" }, [
          el("label", { class: "field" }, [el("span", { text: "Діє до" }), until]),
          el("label", { class: "field" }, [el("span", { text: "Нотатка" }), note]),
        ]),
        el("div", { class: "form-actions" }, [el("button", { class: "btn btn-primary", type: "submit", text: "Зберегти" })]),
      ]);
      return form;
    })(),
  ]);
  root.appendChild(grant);

  const tablePanel = el("section", { class: "panel" }, [
    el("h2", { class: "panel__title", text: "Активні та колишні підписки" }),
    el("div", { class: "table-wrap" }, [el("table", { class: "table", id: "subsTable" })]),
  ]);
  root.appendChild(tablePanel);

  const reqPanel = el("section", { class: "panel" }, [
    el("h2", { class: "panel__title", text: "Запити на доступ" }),
    el("div", { id: "accessReqs" }),
  ]);
  root.appendChild(reqPanel);

  adminListSubscriptions().then((d) => fillTable(d.subscriptions)).catch((err) => toast(err.message, "error"));
  adminListAccessRequests().then((d) => fillRequests(d.requests)).catch(() => {});
}

function fillTable(store) {
  const table = document.getElementById("subsTable");
  if (!table) return;
  clear(table);
  const entries = Object.entries(store || {});
  table.appendChild(el("thead", {}, [el("tr", {}, [
    el("th", { text: "Пошта" }), el("th", { text: "Статус" }),
    el("th", { text: "Діє до" }), el("th", { text: "" }),
  ])]));
  if (!entries.length) {
    table.appendChild(el("tbody", {}, [el("tr", {}, [el("td", { colspan: "4", class: "muted", text: "Поки нікого." })])]));
    return;
  }
  table.appendChild(el("tbody", {}, entries.map(([email, e]) => el("tr", {}, [
    el("td", { text: email }),
    el("td", {}, [el("span", { class: "pill " + (e.status === "active" ? "pill--ok" : "pill--off"), text: e.status })]),
    el("td", { text: e.expires_utc ? fmtDate(e.expires_utc) : "безстроково" }),
    el("td", {}, [el("button", { class: "btn btn-sm btn-danger", text: "Прибрати", onclick: () => {
      if (!confirm("Прибрати підписку для " + email + "?")) return;
      adminRevokeSubscription(email).then((d) => { toast("Прибрано", "ok"); fillTable(d.subscriptions); }).catch((err) => toast(err.message, "error"));
    } })]),
  ]))));
}

function fillRequests(list) {
  const host = document.getElementById("accessReqs");
  if (!host) return;
  clear(host);
  if (!list || !list.length) {
    host.appendChild(el("p", { class: "muted", text: "Нових запитів немає." }));
    return;
  }
  list.forEach((r) => {
    host.appendChild(el("div", { class: "req" }, [
      el("div", {}, [
        el("strong", { text: r.name || r.email }),
        el("span", { class: "muted", text: " " + r.email }),
        r.message ? el("p", { class: "req__msg", text: r.message }) : null,
      ]),
      el("button", { class: "btn btn-sm btn-primary", text: "Видати доступ", onclick: () => {
        adminGrantSubscription({ email: r.email })
          .then((d) => { toast("Доступ видано", "ok"); fillTable(d.subscriptions); })
          .catch((err) => toast(err.message, "error"));
      } }),
    ]));
  });
}
