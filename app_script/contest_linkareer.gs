// ============================================================
// 링커리어 공모전 수집 → 슬랙 전송 + 시트 기록
// 시트 열: A 수집시간 | B 공모전 제목 | C 주소 | D 시작일 | E 마감일
//
// 설정 (스크립트 속성: 프로젝트 설정 > 스크립트 속성)
//   SLACK_WEBHOOK_URL : 슬랙 웹훅 주소 (코드에 직접 쓰지 않는다)
//   TEST_MODE              : (선택) "true"이면 테스트 모드. 아래 '테스트 모드' 참고
//   SLACK_WEBHOOK_URL_TEST : (테스트 모드용) 테스트 채널 웹훅 주소
// ============================================================

var SHEET_NAME = "시트1";               // 기록할 탭 이름. 없으면 활성 시트 사용
var KEYWORDS_KO = ["인공지능", "데이터"]; // 한글 키워드: 부분 문자열 일치
var KEYWORDS_EN = ["AI"];               // 영문 키워드: 독립된 단어일 때만 일치 (TRAIN, MAIN 제외)
var TEST_MAX_SEND = 3;                  // 테스트 모드에서 보내는 최신 공고 수
var SENT_IDS_KEEP = 200;                // 중복 방지용으로 기억할 ID 수

var LINKAREER_API_URL = "https://api.linkareer.com/graphql?operationName=ActivityList_Activities&variables=%7B%22filterBy%22%3A%7B%22status%22%3A%22OPEN%22%2C%22activityTypeID%22%3A%223%22%2C%22categoryIDs%22%3A%5B%2235%22%5D%2C%22simpleApplyFilter%22%3Anull%7D%2C%22pageSize%22%3A20%2C%22page%22%3A1%2C%22activityOrder%22%3A%7B%22field%22%3A%22CREATED_AT%22%2C%22direction%22%3A%22DESC%22%7D%7D&extensions=%7B%22persistedQuery%22%3A%7B%22version%22%3A1%2C%22sha256Hash%22%3A%222c08975fee8ab40c8a099c9a78adf8c4a9da63ce605f2cce4e49d4b26c99eba4%22%7D%7D";

// ===================== 메인 =====================
function fetchAndSendContestToSlack() {
  Logger.log("▶ 공모전 수집 시작");
  try {
    var webhook = getWebhook_();
    if (!webhook) return;
    var testMode = isTestMode_();

    var sheet = getSheet_();
    var activities = fetchActivities_();
    if (activities === null) return;
    Logger.log("받은 공고 수: " + activities.length);

    var matching = activities.filter(function (a) { return isMatch_(a.title || ""); });
    Logger.log("키워드 일치 공고 수: " + matching.length);
    if (matching.length === 0) return;

    var props = PropertiesService.getScriptProperties();
    var sentIds = JSON.parse(props.getProperty("sentIdsArray") || "[]");
    var sheetLinks = existingLinks_(sheet); // 속성이 지워져도 시트 기준으로 중복 방지
    var sentCount = 0;

    // 테스트 모드: 최신 N건을 중복 여부와 관계없이 테스트 웹훅으로만 보낸다
    var queue = (testMode ? matching.slice(0, TEST_MAX_SEND) : matching.slice()).reverse(); // 오래된 것부터
    for (var j = 0; j < queue.length; j++) {
      var c = queue[j];
      var link = "https://linkareer.com/activity/" + c.id;
      if (!testMode && (sentIds.indexOf(String(c.id)) !== -1 || sheetLinks[link])) continue;

      var title = (testMode ? "🧪 [TEST] " : "") + (c.title || "새로운 AI/데이터 공모전");
      var dates = extractDates_(c, title);
      var poster = (c.thumbnailImage && c.thumbnailImage.url) ? c.thumbnailImage.url : "https://linkareer.com/favicon.ico";

      var ok = postSlack_(webhook, {
        // text는 conversations.history에서 읽을 수 있도록 넣는 대체 문구 (봇 수집용)
        "text": title + "\n" + link,
        "blocks": [
          { "type": "section", "text": { "type": "mrkdwn", "text": "*" + title + "*" } },
          { "type": "image", "title": { "type": "plain_text", "text": "공모전 포스터", "emoji": true }, "image_url": poster, "alt_text": "공모전 포스터" },
          { "type": "actions", "elements": [{ "type": "button", "text": { "type": "plain_text", "text": "상세 내용 보기", "emoji": true }, "url": link, "action_id": "button_click" }] }
        ]
      });
      if (!ok) continue; // 전송 실패 시 기록하지 않아 다음 실행에서 다시 시도

      if (!testMode) {
        var now = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");
        sheet.appendRow([now, title, link, dates.start, dates.end]);
        sentIds.push(String(c.id));
      }
      sentCount++;
      Logger.log("✅ 전송·기록: " + title + " | 시작 " + (dates.start || "-") + " 마감 " + (dates.end || "-"));
      Utilities.sleep(1500);
    }

    if (sentCount > 0 && !testMode) {
      if (sentIds.length > SENT_IDS_KEEP) sentIds = sentIds.slice(-SENT_IDS_KEEP);
      props.setProperty("sentIdsArray", JSON.stringify(sentIds));
    }
    Logger.log("■ 완료: 새로 보낸 공고 " + sentCount + "건");
  } catch (e) {
    Logger.log("❌ 에러: " + e.toString());
  }
}

// ===================== 응답 필드 점검 (처음 한 번 직접 실행) =====================
// 첫 공고의 키와 값을 로그에 남겨 시작일/마감일 필드 이름을 확인한다.
function debugShowFields() {
  var activities = fetchActivities_();
  if (!activities || activities.length === 0) { Logger.log("공고가 없습니다."); return; }
  var node = activities[0];
  Logger.log("키 목록: " + Object.keys(node).join(", "));
  Object.keys(node).forEach(function (k) {
    var v = node[k];
    var s = (v !== null && typeof v === "object") ? JSON.stringify(v) : String(v);
    Logger.log(k + " = " + s.substring(0, 120));
  });
  var d = extractDates_(node, node.title || "");
  Logger.log("추출한 날짜 → 시작: " + (d.start || "(없음)") + " / 마감: " + (d.end || "(없음)") + " / 출처: " + d.source);
}

// ===================== 내부 함수 =====================
function getSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(SHEET_NAME) || ss.getActiveSheet();
}

function fetchActivities_() {
  var res = UrlFetchApp.fetch(LINKAREER_API_URL, {
    "method": "get",
    "headers": {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Accept": "*/*", "Referer": "https://linkareer.com/", "Origin": "https://linkareer.com"
    },
    "muteHttpExceptions": true
  });
  var code = res.getResponseCode();
  var json;
  try { json = JSON.parse(res.getContentText()); } catch (e) { Logger.log("❌ 응답 JSON 파싱 실패 (HTTP " + code + ")"); return null; }
  if (json.errors) {
    // persisted query 해시가 만료되면 여기로 온다
    Logger.log("❌ API 오류: " + JSON.stringify(json.errors).substring(0, 300));
    return null;
  }
  if (!json.data || !json.data.activities || !json.data.activities.nodes) {
    Logger.log("❌ 응답에 activities.nodes가 없습니다 (HTTP " + code + ")");
    return null;
  }
  return json.data.activities.nodes;
}

function isMatch_(title) {
  var hasKo = KEYWORDS_KO.some(function (k) { return title.indexOf(k) !== -1; });
  if (hasKo) return true;
  return KEYWORDS_EN.some(function (k) {
    return new RegExp("(^|[^A-Za-z])" + k + "([^A-Za-z]|$)", "i").test(title);
  });
}

function existingLinks_(sheet) {
  var map = {};
  var last = sheet.getLastRow();
  if (last < 2) return map;
  sheet.getRange(2, 3, last - 1, 1).getValues().forEach(function (r) { map[String(r[0])] = true; });
  return map;
}

function postSlack_(webhook, payload) {
  try {
    var r = UrlFetchApp.fetch(webhook, { "method": "post", "contentType": "application/json", "payload": JSON.stringify(payload), "muteHttpExceptions": true });
    if (r.getResponseCode() !== 200) { Logger.log("❌ 슬랙 전송 실패: HTTP " + r.getResponseCode()); return false; }
    return true;
  } catch (e) { Logger.log("❌ 슬랙 전송 예외: " + e.toString()); return false; }
}

// 시작일/마감일을 API 응답에서 찾고, 없으면 제목의 (~M/D) 표기로 보완한다.
function extractDates_(node, title) {
  var start = "", end = "", source = "none";
  var startRe = /^(recruit)?(start|open)(at|date|time)?$/i;
  var endRe = /^(recruit)?(close|end|deadline)(at|date|time)?$/i;
  Object.keys(node).forEach(function (k) {
    if (!start && startRe.test(k)) start = toDateStr_(node[k]);
    if (!end && endRe.test(k)) end = toDateStr_(node[k]);
  });
  if (start || end) source = "api";
  if (!end) {
    var t = titleDeadline_(title);
    if (t) { end = t; source = "title"; }
  }
  return { start: start, end: end, source: source };
}

function toDateStr_(v) {
  if (v === null || v === undefined || v === "") return "";
  var d;
  if (typeof v === "number") d = new Date(v < 1e12 ? v * 1000 : v);
  else d = new Date(String(v));
  if (isNaN(d.getTime())) return "";
  return Utilities.formatDate(d, "GMT+9", "yyyy-MM-dd");
}

// "(~11/20)" 형식. 수집 시점보다 이전 월이면 다음 해로 본다.
function titleDeadline_(title) {
  var m = String(title).match(/\(~\s*(\d{1,2})\/(\d{1,2})\)/);
  if (!m) return "";
  var now = new Date();
  var year = Number(Utilities.formatDate(now, "GMT+9", "yyyy"));
  var curMonth = Number(Utilities.formatDate(now, "GMT+9", "M"));
  var month = Number(m[1]), day = Number(m[2]);
  if (month < curMonth) year += 1;
  return year + "-" + ("0" + month).slice(-2) + "-" + ("0" + day).slice(-2);
}

// ===================== 테스트 모드 =====================
// 편집기에서 testFetchAndSendContestToSlack() 를 실행하면 속성을 바꾸지 않고도 테스트 모드로 1회 실행된다.
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
function testFetchAndSendContestToSlack() {
  FORCE_TEST_ = true;
  fetchAndSendContestToSlack();
}
