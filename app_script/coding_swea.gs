// ============================================================
// SWEA 오늘의 문제 (월·목) → 슬랙 전송
// 시트 열: A 문제번호 | B 제목 | C 티어(D1~D8) | D 참여 인원 | E 정답률 | F 완료여부 | G 해시코드
//
// 스크립트 속성: SLACK_WEBHOOK_URL (코드에 직접 쓰지 않는다)
// 테스트 모드: 스크립트 속성 TEST_MODE=true, SLACK_WEBHOOK_URL_TEST (아래 '테스트 모드' 참고)
// 메시지 형식은 슬랙 봇의 파서가 의존하므로 바꿀 때는 봇의 fixture와 함께 고친다.
// 레벨 표기: SWEA D(N) → "레벨 N-1" (D1 → 레벨 0)
// ============================================================

var SWEA_SHEET_NAME = "SWEA";
var SEND_DAYS = [1, 4]; // 0:일 1:월 2:화 3:수 4:목 5:금 6:토

function sendDailySWEA() {
  Logger.log("▶ SWEA 전송 시작");
  try {
    var day = Number(Utilities.formatDate(new Date(), "GMT+9", "u")) % 7; // u: 1(월)~7(일) → 0(일)~6(토)
    var testMode = isTestMode_();   // 테스트 모드는 요일과 관계없이 보내고 '완료' 표시는 하지 않는다
    if (!testMode && SEND_DAYS.indexOf(day) === -1) { Logger.log("오늘은 발송 요일이 아닙니다."); return; }

    var webhook = getWebhook_();
    if (!webhook) return;

    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SWEA_SHEET_NAME);
    if (!sheet) { Logger.log("❌ 시트 '" + SWEA_SHEET_NAME + "'를 찾을 수 없습니다."); return; }

    var next = getNextProblem_(sheet);
    if (!next) {
      post_(webhook, { "text": "⚠️ [알림] SWEA 시트에 등록된 모든 문제를 풀었습니다!",
        "blocks": [{ "type": "section", "text": { "type": "mrkdwn", "text": "⚠️ *[알림]*\nSWEA 시트에 등록된 모든 문제를 풀었습니다!" } }] });
      return;
    }

    var url = "https://swexpertacademy.com/main/code/problem/problemDetail.do?contestProbId=" + next.hashCode;
    var header = (testMode ? "🧪 [TEST] " : "") + "오늘의 SWEA 문제  -  " + next.sendCount;
    var dateStr = Utilities.formatDate(new Date(), "GMT+9", "yy/MM/dd");
    var participants = Number(next.participants).toLocaleString();
    var accuracy = String(next.accuracy);
    if (accuracy.indexOf("%") === -1) accuracy = (parseFloat(accuracy) * 100).toFixed(2) + "%";

    var line1 = "*`" + formatTier_(next.tier) + "`*  <" + url + "|" + next.probNum + "번 : " + next.title + ">";
    var line2 = "참여 인원 : *" + participants + "명*\t정답률 : *" + accuracy + "*\t전송일 : *" + dateStr + "*";

    var ok = post_(webhook, {
      "text": header + "\n" + line1 + "\n" + line2, // conversations.history용 대체 문구
      "blocks": [
        { "type": "header", "text": { "type": "plain_text", "text": header, "emoji": true } },
        { "type": "section", "text": { "type": "mrkdwn", "text": line1 } },
        { "type": "context", "elements": [{ "type": "mrkdwn", "text": line2 }] }
      ]
    });

    // 전송에 성공했을 때만 완료로 표시한다 (실패 시 다음 실행에서 같은 문제를 다시 보냄)
    if (ok && !testMode) {
      sheet.getRange(next.row, 6).setValue("완료");
      Logger.log("✅ 전송 완료: " + next.probNum + " " + next.title);
    } else if (ok) {
      Logger.log("🧪 테스트 전송 완료(시트 변경 없음): " + next.probNum + " " + next.title);
    }
  } catch (e) {
    Logger.log("❌ 에러: " + e.toString());
  }
}

function formatTier_(tier) {
  if (!tier) return "레벨 -";
  var t = tier.toString().trim().toUpperCase();
  if (t.indexOf("D") === 0) {
    var n = parseInt(t.substring(1), 10) - 1;
    if (!isNaN(n)) return "레벨 " + n; // D1 → 레벨 0
  }
  return t;
}

// 완료가 아닌 첫 행을 돌려준다. 표시는 하지 않는다. sendCount는 완료 행 수 + 1.
function getNextProblem_(sheet) {
  if (sheet.getLastRow() < 2) return null;
  var data = sheet.getRange(2, 1, sheet.getLastRow() - 1, 7).getValues();
  var count = 0;
  for (var i = 0; i < data.length; i++) {
    if (data[i][5] === "완료") { count++; continue; }
    return { row: i + 2, probNum: data[i][0], title: data[i][1], tier: data[i][2],
             participants: data[i][3], accuracy: data[i][4], hashCode: data[i][6], sendCount: count + 1 };
  }
  return null;
}

function post_(webhook, payload) {
  try {
    var r = UrlFetchApp.fetch(webhook, { "method": "post", "contentType": "application/json", "payload": JSON.stringify(payload), "muteHttpExceptions": true });
    if (r.getResponseCode() !== 200) { Logger.log("❌ 슬랙 전송 실패: HTTP " + r.getResponseCode()); return false; }
    return true;
  } catch (e) { Logger.log("❌ 슬랙 전송 예외: " + e.toString()); return false; }
}

// ===================== 테스트 모드 =====================
// 편집기에서 testSendDailySWEA() 를 실행하면 속성을 바꾸지 않고도 테스트 모드로 1회 실행된다.
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
function testSendDailySWEA() {
  FORCE_TEST_ = true;
  sendDailySWEA();
}
