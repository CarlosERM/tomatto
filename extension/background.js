// Tomatto background service worker (Manifest V3).
//
// MV3 service workers are ephemeral (~30s idle => terminated), so all state
// lives in chrome.storage and polling uses chrome.alarms, never setInterval.

const SYNC_API = "http://localhost:3002"; // change here if the Sync API runs elsewhere
const ALARM_NAME = "tomatto-poll";

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
  syncNow();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
  syncNow();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    syncNow();
  }
});

async function syncNow() {
  const stored = await chrome.storage.local.get(["etag", "ruleMap", "nextRuleId"]);

  const headers = stored.etag ? { "If-None-Match": stored.etag } : {};
  let response;
  try {
    response = await fetch(`${SYNC_API}/blocked`, { headers });
  } catch (err) {
    console.warn("[tomatto] Sync API unreachable:", err.message);
    return; // keep current rules; retry on next alarm
  }

  if (response.status === 304) {
    return; // nothing changed — cheap poll
  }
  if (!response.ok) {
    console.warn(`[tomatto] Sync API returned HTTP ${response.status}`);
    return;
  }

  const { version, sites } = await response.json();
  const ruleMap = stored.ruleMap ?? {}; // key "domain|subs" -> dNR rule id
  let nextRuleId = stored.nextRuleId ?? 1;

  const desired = new Map(
    (sites ?? []).map((s) => [`${s.domain}|${s.include_subdomains ? 1 : 0}`, s])
  );

  // Remove rules that disappeared or changed their subdomain flag.
  const removeRuleIds = [];
  for (const [key, ruleId] of Object.entries(ruleMap)) {
    if (!desired.has(key)) {
      removeRuleIds.push(ruleId);
      delete ruleMap[key];
    }
  }

  // Add rules the Sync API has but we don't.
  const addRules = [];
  for (const [key, site] of desired) {
    if (key in ruleMap) continue;
    const domains = site.include_subdomains ? [site.domain, `*.${site.domain}`] : [site.domain];
    addRules.push({
      id: nextRuleId++,
      priority: 1,
      action: { type: "redirect", redirect: { extensionPath: "blocked.html" } },
      condition: { domains, urlFilter: "*" },
    });
    ruleMap[key] = addRules[addRules.length - 1].id;
  }

  if (removeRuleIds.length > 0 || addRules.length > 0) {
    await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds, addRules });
    console.log(`[tomatto] v${version}: +${addRules.length} -${removeRuleIds.length} rules`);
  }

  await chrome.storage.local.set({
    ruleMap,
    nextRuleId,
    etag: response.headers.get("etag") ?? null,
    lastVersion: version,
  });
}
