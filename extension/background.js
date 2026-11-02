// Tomatto background service worker (Manifest V3).
//
// MV3 service workers are ephemeral (~30s idle => terminated), so all state
// lives in chrome.storage and polling uses chrome.alarms, never setInterval.

const SYNC_API = "http://localhost:3002"; // change here if the Sync API runs elsewhere
const ALARM_NAME = "tomatto-poll";

console.log("[tomatto] worker v5 loaded"); // version banner: distinguishes live code from stale console messages

// Rule-schema version embedded in ruleMap keys. Bump when conditions change;
// instances holding older keys force one full fetch (skipping the ETag) so the
// diff can rebuild every rule — a 304 would otherwise skip migration forever.
const RULE_SCHEMA = "v4";

// Build the dNR condition for one site. Notes from the declarativeNetRequest docs:
// - `domains` is deprecated (Chrome 101+) and matches the request INITIATOR, not
//   the target URL — address-bar navigations would never match it. `requestDomains`
//   matches the request URL's host and implicitly includes all sub-domains.
// - If neither resourceTypes nor excludedResourceTypes is given, main_frame is
//   EXCLUDED — top-level navigation must be listed explicitly to block visits.
function ruleCondition(site) {
  const base = { resourceTypes: ["main_frame", "sub_frame"] };
  if (site.include_subdomains) {
    return { ...base, requestDomains: [site.domain], urlFilter: "*" };
  }
  // Exact host only: anchor scheme + host boundary. regexFilter is matched
  // against the punycode host, which our domains already are.
  const escaped = site.domain.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return { ...base, regexFilter: `^https?://${escaped}([/:?#]|$)` };
}

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

  // If our stored rules predate the current schema, skip the ETag so this poll
  // returns a full snapshot and the diff below can rebuild them.
  const storedKeys = Object.keys(stored.ruleMap ?? {});
  const needsMigration = storedKeys.some((k) => !k.startsWith(`${RULE_SCHEMA}|`));

  const headers = stored.etag && !needsMigration ? { "If-None-Match": stored.etag } : {};
  let response;
  try {
    response = await fetch(`${SYNC_API}/blocked`, { headers });
  } catch (err) {
    console.warn("[tomatto] Sync API unreachable:", err.message);
    return; // keep current rules; retry on next alarm
  }

  if (response.status === 304) {
    console.log("[tomatto] unchanged (304)"); // visible heartbeat: silence != failure
    return; // nothing changed — cheap poll
  }
  if (!response.ok) {
    console.warn(`[tomatto] Sync API returned HTTP ${response.status}`);
    return;
  }

  const { version, sites } = await response.json();
  const ruleMap = stored.ruleMap ?? {}; // key "<schema>|domain|subs" -> dNR rule id
  let nextRuleId = stored.nextRuleId ?? 1;

  const desired = new Map(
    (sites ?? []).map((s) => [`${RULE_SCHEMA}|${s.domain}|${s.include_subdomains ? 1 : 0}`, s])
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
    addRules.push({
      id: nextRuleId++,
      priority: 1,
      // extensionPath must be absolute (leading "/") and the target must be
      // listed in manifest web_accessible_resources.
      action: { type: "redirect", redirect: { extensionPath: "/blocked.html" } },
      condition: ruleCondition(site),
    });
    ruleMap[key] = addRules[addRules.length - 1].id;
  }

  if (removeRuleIds.length > 0 || addRules.length > 0) {
    try {
      await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds, addRules });
      console.log(`[tomatto] v${version}: +${addRules.length} -${removeRuleIds.length} rules`);
    } catch (err) {
      // Don't persist etag/ruleMap for a snapshot we failed to apply — the
      // next alarm will re-fetch and retry instead of silently diverging.
      console.error("[tomatto] updateDynamicRules failed:", err.message);
      return;
    }
  }

  await chrome.storage.local.set({
    ruleMap,
    nextRuleId,
    etag: response.headers.get("etag") ?? null,
    lastVersion: version,
  });
}
