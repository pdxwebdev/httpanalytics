let section = "overview";
let payload = null;

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

function num(value) {
    return Number(value || 0).toLocaleString();
}

function bytes(value) {
    const n = Number(value || 0);
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
    return (n / 1073741824).toFixed(2) + " GB";
}

function when(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return esc(value);
    return date.toLocaleString();
}

function statusPill(code) {
    const n = Number(code || 0);
    const cls = n >= 500 ? "bad" : n >= 400 ? "warn" : "ok";
    return `<span class="pill ${cls}">${n || "-"}</span>`;
}

function rows(items, columns) {
    if (!items || !items.length) return "<p class='muted'>No traffic in this range.</p>";
    const head = columns.map(col => `<th class="${col.right ? "right" : ""}">${col.label}</th>`).join("");
    const body = items.map(item => {
        const cells = columns.map(col => {
            const raw = col.render ? col.render(item) : esc(item[col.key]);
            return `<td class="${col.right ? "right" : ""} ${col.mono ? "mono" : ""}">${raw}</td>`;
        }).join("");
        return `<tr>${cells}</tr>`;
    }).join("");
    return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function chart(series) {
    const max = Math.max(1, ...series.map(point => point.requests || 0));
    if (!series.length) return "<p class='muted'>No samples yet.</p>";
    return `<div class="bars" title="Requests">${series.map(point => {
        const h = Math.max(4, Math.round((point.requests / max) * 120));
        const label = new Date(point.t).toLocaleString();
        return `<i style="height:${h}px" title="${esc(label)} · ${point.requests} req · ${point.visitors} visitors"></i>`;
    }).join("")}</div>`;
}

function stats(data) {
    const cards = [
        ["Requests", num(data.requests), data.error_rate + "% errors"],
        ["Unique visitors", num(data.unique_visitors), num(data.unique_ips) + " IPs"],
        ["Humans / bots", num(data.humans), num(data.bots) + " bot hits"],
        ["Latency", data.avg_ms + " ms avg", data.max_ms + " ms max"],
        ["Transferred", bytes(data.bytes), "response bytes"],
        ["Errors", num(data.errors), "status 400+"],
        ["Paths", num((data.paths || []).length), "top paths shown"],
        ["Referrers", num((data.referers || []).length), "external and internal"],
    ];
    return `<div class="stats">${cards.map(([label, value, note]) =>
        `<div><span>${label}</span><strong>${esc(value)}</strong><em>${esc(note)}</em></div>`
    ).join("")}</div>`;
}

function pathTable(items) {
    return rows(items, [
        { label: "Path", mono: true, render: item => esc(item.key) },
        { label: "Requests", right: true, render: item => num(item.requests) },
        { label: "Visitors", right: true, render: item => num(item.visitors) },
        { label: "Avg", right: true, render: item => item.avg_ms + " ms" },
        { label: "Errors", right: true, render: item => num(item.errors) },
        { label: "Bytes", right: true, render: item => bytes(item.bytes) },
    ]);
}

function countTable(items, label) {
    const max = Math.max(1, ...(items || []).map(item => item.requests || 0));
    return rows(items, [
        { label, mono: true, render: item => esc(item.key || "(none)") },
        { label: "Requests", right: true, render: item => num(item.requests) },
        { label: "", render: item => `<div class="meter"><b style="width:${Math.round(item.requests / max * 100)}%"></b></div>` },
    ]);
}

function liveTable(items) {
    return rows(items, [
        { label: "Time", render: item => when(item.ts) },
        { label: "Method", render: item => esc(item.method) },
        { label: "Path", mono: true, render: item => esc(item.path) },
        { label: "Status", render: item => statusPill(item.status) },
        { label: "ms", right: true, render: item => esc(item.ms) },
        { label: "IP", mono: true, render: item => esc(item.ip) },
        { label: "Visitor", mono: true, render: item => esc(item.vid) },
        { label: "Client", render: item => `${esc(item.browser)}${item.bot ? " <span class='pill warn'>bot</span>" : ""}` },
        { label: "Referrer", render: item => esc(item.referer || "") },
        { label: "Country", render: item => esc(item.country || "") },
    ]);
}

function render() {
    const root = document.getElementById("content");
    const data = payload || {};
    if (section === "paths") {
        root.innerHTML = `<section class="panel"><h2>URLs</h2>${pathTable(data.paths)}</section>
            <div class="cols"><section class="panel"><h2>Methods</h2>${countTable(data.methods, "Method")}</section>
            <section class="panel"><h2>Status</h2>${countTable(data.statuses, "Status")}</section></div>`;
        return;
    }
    if (section === "visitors") {
        root.innerHTML = `${stats(data)}
            <div class="cols"><section class="panel"><h2>Browsers</h2>${countTable(data.browsers, "Browser")}</section>
            <section class="panel"><h2>Countries</h2>${countTable(data.countries, "Country")}</section></div>
            <section class="panel"><h2>Referrers</h2>${pathTable(data.referers)}</section>
            <section class="panel"><h2>User agents</h2>${countTable(data.agents, "Agent")}</section>`;
        return;
    }
    if (section === "live") {
        root.innerHTML = `<section class="panel"><h2>Latest hits</h2><p class="muted">Query strings are not stored.</p>${liveTable(data.live)}</section>`;
        return;
    }
    root.innerHTML = `${stats(data)}
        <section class="panel"><h2>Requests</h2>${chart(data.series || [])}</section>
        <div class="cols"><section class="panel"><h2>Top URLs</h2>${pathTable((data.paths || []).slice(0, 12))}</section>
        <section class="panel"><h2>Status</h2>${countTable(data.statuses, "Status")}</section></div>`;
}

async function refresh() {
    const pill = document.getElementById("live");
    const range = document.getElementById("range").value;
    try {
        const response = await fetch(`/analytics/api/overview?range=${encodeURIComponent(range)}`, { cache: "no-store" });
        if (response.status === 401) {
            window.location = "/operator";
            return;
        }
        if (!response.ok) throw new Error("bad status");
        payload = await response.json();
        pill.textContent = "live";
        pill.classList.add("on");
        render();
    } catch (error) {
        pill.textContent = "offline";
        pill.classList.remove("on");
        document.getElementById("content").innerHTML = "<section class='panel'><h2>Analytics unavailable.</h2></section>";
    }
}

document.querySelectorAll(".top nav a[data-section]").forEach(link => {
    link.addEventListener("click", event => {
        event.preventDefault();
        section = link.dataset.section;
        document.getElementById("nav").classList.remove("open");
        document.querySelectorAll(".top nav a[data-section]").forEach(item => {
            item.classList.toggle("active", item === link);
        });
        render();
    });
});

document.getElementById("range").addEventListener("change", refresh);
refresh();
setInterval(refresh, 15000);
