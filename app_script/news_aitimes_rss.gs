// ============================================================
// AI타임스 / 인공지능신문 RSS 수집 → 슬랙 전송 + 시트 기록
// 같은 코드를 두 스크립트 프로젝트(시트)에 각각 붙여넣고, 스크립트 속성으로 사이트를 고른다.
//
// 시트 열: A 수집시간 | B 기사 제목 | C 주소   (기준 시각은 수집시간. 발행일은 기록하지 않는다)
// 새 기사는 모두 시트에 기록하고, 슬랙에는 최신 MAX_SLACK_POSTS(10)건만 올린다(나머지는 시트에만).
//
// 스크립트 속성 (프로젝트 설정 > 스크립트 속성)
//   SLACK_WEBHOOK_URL : 슬랙 웹훅 주소 (코드에 직접 쓰지 않는다)
//   TEST_MODE              : (선택) "true"이면 테스트 모드. 아래 '테스트 모드' 참고
//   SLACK_WEBHOOK_URL_TEST : (테스트 모드용) 테스트 채널 웹훅 주소
//   AITIMES_SITE      : (선택) "kr"(인공지능신문) 또는 "com"(AI타임스). 없으면 site.gs의 DEFAULT_SITE 사용
// site.gs (프로젝트별, deploy.sh가 생성): var DEFAULT_SITE = "kr" | "com";
// ============================================================

// 기존 트리거(aitimes.com 프로젝트)가 호출하던 함수 이름을 유지한다.
function fetchAITimesAndSendToSlack() { sendAiTimesNews(); }

var SHEET_NAME = "전송기록";   // 없으면 활성 시트 사용
var MAX_SLACK_POSTS = 10;   // 한 번에 슬랙에 올리는 최대 기사 수. 넘치는 새 기사는 시트에만 기록한다(예: 주말에 쌓인 기사)
var MAX_FEED_ITEMS = 100;   // RSS에서 읽는 최대 기사 수(피드는 보통 20~50건)
var TEST_MAX_SEND = 3;      // 테스트 모드에서 보내는 최신 기사 수
var SENT_IDS_KEEP = 500;

var SITES = {
  "kr":  { "host": "https://www.aitimes.kr",  "rss": ["https://www.aitimes.kr/rss/S1N4.xml"] },
  // aitimes.com RSS 경로는 같은 CMS 관례로 추정한 후보들이다. 처음 실행 로그에서 성공한 경로를 확인한다.
  "com": { "host": "https://www.aitimes.com", "rss": ["https://www.aitimes.com/rss/allArticle.xml", "https://www.aitimes.com/rss/S1N24.xml"] }
};

// ===================== 메인 =====================
function sendAiTimesNews() {
  var props = PropertiesService.getScriptProperties();
  var siteKey = props.getProperty("AITIMES_SITE") || DEFAULT_SITE; // DEFAULT_SITE는 프로젝트별 site.gs에 정의
  var site = SITES[siteKey];
  Logger.log("▶ 시작: 사이트=" + siteKey);
  if (!site) { Logger.log("❌ AITIMES_SITE 값이 올바르지 않습니다 (kr 또는 com)"); return; }

  try {
    var webhook = getWebhook_();
    if (!webhook) return;
    var testMode = isTestMode_();

    var articles = fetchRss_(site);
    if (articles === null) return;
    Logger.log("📄 RSS 파싱: " + articles.length + "건");
    if (articles.length === 0) return;

    var sheet = getSheet_();
    var seenIds = {};
    JSON.parse(props.getProperty("sentArticleIds") || "[]").forEach(function (id) { seenIds[id] = true; });
    Object.keys(existingIds_(sheet)).forEach(function (id) { seenIds[id] = true; }); // 시트 기준 중복 방지

    // 새 기사(최신순). 테스트 모드: 최신 N건을 중복 여부와 관계없이 테스트 웹훅으로만 보낸다.
    var fresh = testMode ? articles.slice(0, TEST_MAX_SEND) : articles.filter(function (a) { return !seenIds[a.id]; });
    if (fresh.length === 0) { Logger.log("🆕 새 기사 없음"); return; }

    // 슬랙에는 최신 MAX_SLACK_POSTS건만 올리고, 나머지는 시트에만 기록한다.
    var toPost = testMode ? fresh : fresh.slice(0, MAX_SLACK_POSTS);
    var sheetOnly = testMode ? [] : fresh.slice(MAX_SLACK_POSTS);
    Logger.log("🆕 새 기사 " + fresh.length + "건 (슬랙 " + toPost.length + "건, 시트에만 기록 " + sheetOnly.length + "건)");

    var sent = JSON.parse(props.getProperty("sentArticleIds") || "[]");
    var nowStr = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");
    sheetOnly.reverse().forEach(function (a) {          // 오래된 기사부터 기록. 슬랙에 올리지 않아도 중복 방지 목록에는 넣는다
      sheet.appendRow([nowStr, a.title, a.link]);
      sent.push(a.id);
    });

    toPost.forEach(function (a) { a.imgUrl = fetchOgImage_(a.link); Utilities.sleep(500); });
    toPost.reverse(); // 오래된 기사부터
    var okCount = 0;
    for (var k = 0; k < toPost.length; k++) {
      var a = toPost[k];
      var mrkdwn = "*<" + a.link + "|" + (testMode ? "🧪 [TEST] " : "") + a.title.replace(/[<>|]/g, " ") + ">*\n\n" + a.summary;
      var section = { "type": "section", "text": { "type": "mrkdwn", "text": mrkdwn } };
      if (a.imgUrl) section.accessory = { "type": "image", "image_url": a.imgUrl, "alt_text": "thumbnail" };

      // text는 conversations.history에서 읽을 수 있도록 넣는 대체 문구 (블록과 같은 내용)
      if (!postSlack_(webhook, { "text": mrkdwn, "blocks": [section, { "type": "divider" }] })) continue;

      if (!testMode) {
        sheet.appendRow([nowStr, a.title, a.link]);
        sent.push(a.id);
      }
      okCount++;
      Utilities.sleep(2000);
    }

    if (!testMode) {
      if (sent.length > SENT_IDS_KEEP) sent = sent.slice(-SENT_IDS_KEEP);
      props.setProperty("sentArticleIds", JSON.stringify(sent));
    }
    Logger.log("■ 완료: 슬랙 " + okCount + "건 전송" + (testMode ? "(테스트)" : ", 시트에만 " + sheetOnly.length + "건 기록"));
  } catch (e) {
    Logger.log("❌ 에러: " + e.toString());
  }
}

// ===================== RSS =====================
function fetchRss_(site) {
  for (var i = 0; i < site.rss.length; i++) {
    var url = site.rss[i];
    var res = UrlFetchApp.fetch(url, { "muteHttpExceptions": true, "headers": { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" } });
    var code = res.getResponseCode();
    var xml = res.getContentText("UTF-8");
    if (code === 200 && xml.indexOf("<item>") !== -1) {
      Logger.log("RSS 성공: " + url);
      return parseItems_(xml, site);
    }
    Logger.log("RSS 실패: " + url + " (HTTP " + code + ", item 없음=" + (xml.indexOf("<item>") === -1) + ")");
  }
  Logger.log("❌ 모든 RSS 경로가 실패했습니다. 사이트가 RSS 경로를 바꿨는지 확인하세요.");
  return null;
}

function parseItems_(xml, site) {
  var items = xml.split(/<item>/);
  var out = [];
  for (var i = 1; i < items.length && out.length < MAX_FEED_ITEMS; i++) {
    var it = items[i];
    var title = cdata_(it, "title"), link = cdata_(it, "link"), desc = cdata_(it, "description");
    if (!title || !link) continue;
    var m = link.match(/idxno=(\d+)/);
    if (!m) continue; // 기사 번호가 없으면 중복 판별이 어려워 건너뜀
    var summary = desc.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    if (summary.length > 120) summary = summary.substring(0, 120) + "...";
    out.push({
      id: m[1],
      title: decode_(title.trim()),
      link: site.host + "/news/articleView.html?idxno=" + m[1], // 항상 같은 형식으로 통일
      summary: decode_(summary),
      imgUrl: ""
    });
  }
  return out;
}

function cdata_(item, tag) {
  var re = new RegExp("<" + tag + ">(?:<!\\[CDATA\\[([\\s\\S]*?)\\]\\]>|([\\s\\S]*?))</" + tag + ">");
  var m = item.match(re);
  return m ? (m[1] !== undefined ? m[1] : m[2]) : "";
}

function fetchOgImage_(url) {
  try {
    var r = UrlFetchApp.fetch(url, { "muteHttpExceptions": true, "followRedirects": true, "headers": { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" } });
    if (r.getResponseCode() !== 200) return "";
    var html = r.getContentText("UTF-8");
    var m = html.match(/<meta[^>]*property=["']og:image["'][^>]*content=["']([^"']+)["']/i)
         || html.match(/<meta[^>]*content=["']([^"']+)["'][^>]*property=["']og:image["']/i)
         || html.match(/<meta[^>]*name=["']twitter:image["'][^>]*content=["']([^"']+)["']/i);
    return m ? m[1] : "";
  } catch (e) { return ""; }
}

// ===================== 시트·슬랙·유틸 =====================
function getSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(SHEET_NAME) || ss.getActiveSheet();
}

function existingIds_(sheet) {
  var map = {};
  var last = sheet.getLastRow();
  if (last < 2) return map;
  sheet.getRange(2, 3, last - 1, 1).getValues().forEach(function (r) {
    var m = String(r[0]).match(/idxno=(\d+)/);
    if (m) map[m[1]] = true;
  });
  return map;
}

function postSlack_(webhook, payload) {
  try {
    var r = UrlFetchApp.fetch(webhook, { "method": "post", "contentType": "application/json", "payload": JSON.stringify(payload), "muteHttpExceptions": true });
    if (r.getResponseCode() !== 200) { Logger.log("❌ 슬랙 전송 실패: HTTP " + r.getResponseCode()); return false; }
    return true;
  } catch (e) { Logger.log("❌ 슬랙 전송 예외: " + e.toString()); return false; }
}

function decode_(t) {
  return t.replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}


// ===================== 테스트 모드 =====================
// 편집기에서 testSendAiTimesNews() 를 실행하면 속성을 바꾸지 않고도 테스트 모드로 1회 실행된다.
// (또는 스크립트 속성 TEST_MODE=true) SLACK_WEBHOOK_URL_TEST(테스트 채널 웹훅)로만 보내고,
// 시트 기록, 중복 방지 기록, '완료' 표시를 하지 않는다. 운영 데이터가 바뀌지 않는다.
var FORCE_TEST_ = false;   // test… 함수가 true로 켠다(실행이 끝나면 사라지므로 운영 실행에는 영향 없음)
function isTestMode_() {
  return FORCE_TEST_ || PropertiesService.getScriptProperties().getProperty("TEST_MODE") === "true";
}

function getWebhook_() {
  var key = isTestMode_() ? "SLACK_WEBHOOK_URL_TEST" : "SLACK_WEBHOOK_URL";
  var url = PropertiesService.getScriptProperties().getProperty(key);
  if (!url) { Logger.log("❌ 스크립트 속성 " + key + "이(가) 설정되지 않았습니다."); return null; }
  if (isTestMode_()) Logger.log("🧪 TEST_MODE: 테스트 웹훅으로만 전송하고 시트·기록·완료 표시는 변경하지 않습니다.");
  return url;
}

// 편집기 함수 목록에서 골라 실행하는 테스트 진입점: 테스트 웹훅으로만 보내고 시트·기록·완료 표시를 바꾸지 않는다.
// 사전 조건: 스크립트 속성 SLACK_WEBHOOK_URL_TEST
function testSendAiTimesNews() {
  FORCE_TEST_ = true;
  sendAiTimesNews();
}

// ===================== 트리거 설정 =====================
// 편집기에서 setupNewsTriggers() 를 한 번 실행하면 아래 일정으로 시간 트리거를 만든다.
// 기존에 이 스크립트를 실행하던 시간 트리거(sendAiTimesNews, fetchAITimesAndSendToSlack)는 먼저 지운다.
// 다시 실행해도 중복되지 않는다. 처음 실행하면 "트리거 관리" 권한 승인을 한 번 묻는다.
// 실행 시각은 프로젝트 시간대(Asia/Seoul)이고, 구글이 지정 시각 전후 약 15분 안에서 실행한다.
var TRIGGER_HOURS = [9, 13, 18];            // 출근, 점심, 퇴근
var TRIGGER_WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"];   // 평일만. 주말을 넣으려면 "SATURDAY", "SUNDAY" 추가
var TRIGGER_HANDLER = "sendAiTimesNews";
var TRIGGER_OLD_HANDLERS = ["sendAiTimesNews", "fetchAITimesAndSendToSlack"];

function setupNewsTriggers() {
  var removed = 0, created = 0;
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getEventType() === ScriptApp.EventType.CLOCK && TRIGGER_OLD_HANDLERS.indexOf(t.getHandlerFunction()) !== -1) {
      ScriptApp.deleteTrigger(t);
      removed++;
    }
  });
  TRIGGER_WEEKDAYS.forEach(function (day) {
    TRIGGER_HOURS.forEach(function (hour) {
      ScriptApp.newTrigger(TRIGGER_HANDLER).timeBased().onWeekDay(ScriptApp.WeekDay[day]).atHour(hour).create();
      created++;
    });
  });
  Logger.log("✅ 트리거 설정 완료: 기존 " + removed + "개 삭제, 새로 " + created + "개 생성 (" + TRIGGER_WEEKDAYS.length + "일 × " + TRIGGER_HOURS.join("·") + "시)");
}

// 현재 트리거 목록을 로그로 확인한다(어떤 함수가 몇 개 걸려 있는지).
function logTriggers() {
  var by = {};
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var k = t.getHandlerFunction() + " [" + t.getEventType() + "]";
    by[k] = (by[k] || 0) + 1;
  });
  Logger.log("트리거 현황: " + JSON.stringify(by));
}
