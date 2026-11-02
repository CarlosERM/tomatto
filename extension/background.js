// Tomatto background service worker (Manifest V3).
//
// MV3 service workers are ephemeral (~30s idle => terminated), so persistent
// state lives in chrome.storage and polling uses chrome.alarms, never setInterval.
//
// v7 design: on every full snapshot we REBUILD all dynamic rules from scratch
// (the canonical docs pattern: getDynamicRules -> remove all -> add new). No
// cached ruleMap is trusted, so Chrome's real rule state can never drift from
// what storage "believes" — the class of bug that plagued v4-v6.

const SYNC_API = "http://localhost:3002"; // change here if the Sync API runs elsewhere
const ALARM_NAME = "tomatto-poll";

console.log("[tomatto] worker v8 loaded");

// Debug aid for unpacked extensions (declarativeNetRequestFeedback permission):
// logs EVERY request this extension's rules match. If a visit produces no
// "matched" line, the rule never fired -> condition problem. If it fires but
// the page still loads -> redirect application problem.
chrome.declarativeNetRequest.onRuleMatchedDebug.addListener((info) => {
  console.log("[tomatto] matched:", info.rule.ruleId, info.request.url);
});

// Build the dNR condition for one site using the canonical ad-blocker form:
// urlFilter "||domain/" = domain anchor + path boundary (matches host and all
// sub-domains; '||example.com/' does NOT match example.company).
// resourceTypes must list main_frame explicitly or top-level visits are excluded.
function ruleCondition(site) {
  const base = { resourceTypes: ["main_frame", "sub_frame"] };
  if (site.include_subdomains) {
    return { ...base, urlFilter: `||${site.domain}/` };
  }
  // Exact host only: anchor scheme + host boundary. regexFilter is matched
  // against the punycode host, which our domains already are.
  const escaped = site.domain.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return { ...base, regexFilter: `^https?://${escaped}([/:?#]|$)` };
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
  syncNow({ forceFull: true }); // startup is authoritative: never trust cached state
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
  syncNow({ forceFull: true });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    syncNow();
  }
});

async function syncNow({ forceFull = false } = {}) {
  const stored = await chrome.storage.local.get(["etag", "nextRuleId"]);

  const headers = !forceFull && stored.etag ? { "If-None-Match": stored.etag } : {};
  let response;
  try {
    response = await fetch(`${SYNC_API}/blocked`, { headers });
  } catch (err) {
    console.warn("[tomatto] Sync API unreachable:", err.message);
    return; // keep current rules; retry on next alarm
  }

  if (response.status === 304) {
    console.log("[tomatto] unchanged (304)");
    return;
  }
  if (!response.ok) {
    console.warn(`[tomatto] Sync API returned HTTP ${response.status}`);
    return;
  }

  const { version, sites } = await response.json();

  // Rebuild everything from the snapshot — source of truth is Chrome itself.
  const existing = await chrome.declarativeNetRequest.getDynamicRules();
  let nextRuleId = Math.max(stored.nextRuleId ?? 1, ...existing.map((r) => r.id + 1), 1);

  const addRules = (sites ?? []).map((site) => ({
    id: nextRuleId++,
    priority: 1,
    // extensionPath must be absolute (leading "/") and the target must be
    // listed in manifest web_accessible_resources.
    action: { type: "redirect", redirect: { extensionPath: "/blocked.html" } },
    condition: ruleCondition(site),
  }));

  try {
    await chrome.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: existing.map((r) => r.id),
      addRules,
    });
    console.log(`[tomatto] v${version}: installed ${addRules.length} rules (${JSON.stringify(sites?.map((s) => s.domain))})`);
  } catch (err) {
    // Don't persist the etag for a snapshot we failed to apply — the next poll
    // re-fetches and retries instead of silently diverging.
    console.error("[tomatto] updateDynamicRules failed:", err.message);
    return;
  }

  await chrome.storage.local.set({
    nextRuleId,
    etag: response.headers.get("etag") ?? null,
    lastVersion: version,
  });
}
