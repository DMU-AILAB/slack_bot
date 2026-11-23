// Apps Script 전역(UrlFetchApp 등)을 모의해 .gs 파일의 TEST_MODE 동작을 Node에서 검증한다.
// 사용: node harness.js  → 시나리오별 결과를 JSON으로 출력
const fs = require("fs"), path = require("path"), vm = require("vm");
const SRC = path.resolve(__dirname, "../../app_script");
const RealDate = Date;

function fmt(date, f) {
  const d = new RealDate(date.getTime() + 9 * 3600e3), p = (n, w = 2) => String(n).padStart(w, "0");
  const dow = d.getUTCDay() === 0 ? 7 : d.getUTCDay();
  return f.replace(/yyyy/g, d.getUTCFullYear()).replace(/yy/g, p(d.getUTCFullYear() % 100)).replace(/MM/g, p(d.getUTCMonth() + 1))
    .replace(/dd/g, p(d.getUTCDate())).replace(/HH/g, p(d.getUTCHours())).replace(/mm/g, p(d.getUTCMinutes()))
    .replace(/\bM\b/g, d.getUTCMonth() + 1).replace(/\bu\b/g, dow);
}

const mkRss = n => `<rss><channel>${Array.from({ length: n }, (_, k) => k + 1).map(i => `<item><title><![CDATA[기사 ${i}]]></title><link>https://www.aitimes.kr/news/articleView.html?idxno=${100 + i}</link><description><![CDATA[요약 ${i}]]></description><pubDate>Sat, 21 Nov 2026 12:00:00 +0900</pubDate></item>`).join("")}</channel></rss>`;
const RSS = mkRss(5);
const LK = JSON.stringify({ data: { activities: { nodes: [
  { id: "1", title: "의료 AI 해커톤", recruitCloseAt: 1796050799999, thumbnailImage: { url: "http://p/1.png" } },
  { id: "2", title: "데이터 경진대회 (~12/31)" },
  { id: "3", title: "TRAIN 철도 대회" } ] } } });

function run({ file, extra = "", fn, props = {}, now = "2026-11-21T03:00:00Z", rows = [], sheetName, triggers = [], rssCount = 5 }) {
  const out = { posts: [], appended: [], setValues: [], propSets: [], logs: [], deleted: [], created: [] };
  const store = { ...props };
  const sheet = {
    appendRow: r => out.appended.push(r), getLastRow: () => rows.length + 1,
    getRange: (r, c, nr, nc) => ({
      getValues: () => rows.map(x => x.slice(0, nc || x.length)),
      setValue: v => out.setValues.push([r, c, v]) }) };
  const FakeDate = class extends RealDate { constructor(...a) { a.length ? super(...a) : super(now); } static now() { return new RealDate(now).getTime(); } };
  const ctx = vm.createContext({
    Date: FakeDate, JSON, Math, console, Array, Object, String, Number, RegExp, parseInt, parseFloat, isNaN, encodeURIComponent,
    Logger: { log: m => out.logs.push(String(m)) },
    Utilities: { sleep() {}, formatDate: (d, tz, f) => fmt(d, f) },
    ScriptApp: {
      EventType: { CLOCK: "CLOCK", ON_OPEN: "ON_OPEN" },
      WeekDay: { MONDAY: "MON", TUESDAY: "TUE", WEDNESDAY: "WED", THURSDAY: "THU", FRIDAY: "FRI", SATURDAY: "SAT", SUNDAY: "SUN" },
      getProjectTriggers: () => triggers.map(t => ({ getHandlerFunction: () => t.fn, getEventType: () => t.type, _t: t })),
      deleteTrigger: t => out.deleted.push(t._t.fn + "/" + t._t.type),
      newTrigger: fn => { const rec = { fn }; const b = {
        timeBased: () => b, onWeekDay: d => { rec.day = d; return b; }, atHour: h => { rec.hour = h; return b; },
        create: () => { out.created.push(rec); return {}; } }; return b; } },
    PropertiesService: { getScriptProperties: () => ({
      getProperty: k => (k in store ? store[k] : null), setProperty: (k, v) => { store[k] = v; out.propSets.push(k); } }) },
    SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: n => (!sheetName || n === sheetName ? sheet : null), getActiveSheet: () => sheet }) },
    UrlFetchApp: { fetch: (url, o) => {
      if (/^https:\/\/hooks\.test\//.test(url)) { out.posts.push({ url, text: JSON.parse(o.payload).text }); return { getResponseCode: () => 200 }; }
      if (/api\.linkareer\.com/.test(url)) return { getResponseCode: () => 200, getContentText: () => LK };
      if (/\/rss\//.test(url)) return { getResponseCode: () => 200, getContentText: () => (rssCount === 5 ? RSS : mkRss(rssCount)) };
      return { getResponseCode: () => 200, getContentText: () => '<meta property="og:image" content="http://img/x.jpg">' };
    } } });
  vm.runInContext(fs.readFileSync(path.join(SRC, file), "utf8") + "\n" + extra, ctx);
  try { vm.runInContext(fn + "()", ctx); } catch (e) { out.logs.push("THROW " + e.message); }
  return out;
}

const PROD = { SLACK_WEBHOOK_URL: "https://hooks.test/PROD" }, TEST = { TEST_MODE: "true", SLACK_WEBHOOK_URL_TEST: "https://hooks.test/TEST" };
const PRG = [["181936", "공배수", "Lv. 0", 55278, "89.00%", "완료"], ["181937", "다음 문제", "Lv. 1", 1000, 0.5, ""]];
const SW = [["6329", "연습", "D2", 1204, "70.21%", "완료", "AV5abc"], ["6330", "다음", "D3", 500, 0.4, "", "AV5def"]];
const SAT = "2026-11-21T03:00:00Z", TUE = "2026-11-17T03:00:00Z", MON = "2026-11-16T03:00:00Z";

const res = {
  contest_normal: run({ file: "contest_linkareer.gs", fn: "fetchAndSendContestToSlack", props: PROD, sheetName: "시트1" }),
  contest_test: run({ file: "contest_linkareer.gs", fn: "fetchAndSendContestToSlack", props: { ...PROD, ...TEST, sentIdsArray: '["1","2"]' }, sheetName: "시트1" }),
  contest_test_no_webhook: run({ file: "contest_linkareer.gs", fn: "fetchAndSendContestToSlack", props: { TEST_MODE: "true", ...PROD }, sheetName: "시트1" }),
  news_normal: run({ file: "news_aitimes_rss.gs", extra: 'var DEFAULT_SITE="kr";', fn: "sendAiTimesNews", props: PROD, sheetName: "전송기록" }),
  news_test: run({ file: "news_aitimes_rss.gs", extra: 'var DEFAULT_SITE="kr";', fn: "sendAiTimesNews", props: { ...PROD, ...TEST, sentArticleIds: '["101","102","103","104","105"]' }, sheetName: "전송기록" }),
  prog_sat_normal: run({ file: "coding_programmers.gs", fn: "sendDailyProgrammers", props: PROD, now: SAT, rows: PRG, sheetName: "Programmers" }),
  prog_sat_test: run({ file: "coding_programmers.gs", fn: "sendDailyProgrammers", props: { ...PROD, ...TEST }, now: SAT, rows: PRG, sheetName: "Programmers" }),
  prog_tue_normal: run({ file: "coding_programmers.gs", fn: "sendDailyProgrammers", props: PROD, now: TUE, rows: PRG, sheetName: "Programmers" }),
  swea_tue_normal: run({ file: "coding_swea.gs", fn: "sendDailySWEA", props: PROD, now: TUE, rows: SW, sheetName: "SWEA" }),
  swea_mon_normal: run({ file: "coding_swea.gs", fn: "sendDailySWEA", props: PROD, now: MON, rows: SW, sheetName: "SWEA" }),
  // 속성 TEST_MODE 없이 test… 함수만으로 테스트 모드가 켜지는지(운영 속성: 테스트 웹훅만 있음)
  contest_wrapper: run({ file: "contest_linkareer.gs", fn: "testFetchAndSendContestToSlack", props: { SLACK_WEBHOOK_URL: "https://hooks.test/PROD", SLACK_WEBHOOK_URL_TEST: "https://hooks.test/TEST" }, sheetName: "시트1" }),
  news_wrapper: run({ file: "news_aitimes_rss.gs", extra: 'var DEFAULT_SITE="kr";', fn: "testSendAiTimesNews", props: { SLACK_WEBHOOK_URL: "https://hooks.test/PROD", SLACK_WEBHOOK_URL_TEST: "https://hooks.test/TEST" }, sheetName: "전송기록" }),
  prog_wrapper_sat: run({ file: "coding_programmers.gs", fn: "testSendDailyProgrammers", props: { SLACK_WEBHOOK_URL: "https://hooks.test/PROD", SLACK_WEBHOOK_URL_TEST: "https://hooks.test/TEST" }, now: SAT, rows: PRG, sheetName: "Programmers" }),
  swea_wrapper_sat: run({ file: "coding_swea.gs", fn: "testSendDailySWEA", props: { SLACK_WEBHOOK_URL: "https://hooks.test/PROD", SLACK_WEBHOOK_URL_TEST: "https://hooks.test/TEST" }, now: SAT, rows: SW, sheetName: "SWEA" }),
  prog_after_wrapper_tue_normal: run({ file: "coding_programmers.gs", fn: "testSendDailyProgrammers", extra: "FORCE_TEST_ = false;", props: PROD, now: TUE, rows: PRG, sheetName: "Programmers" }),
  news_setup_triggers: run({ file: "news_aitimes_rss.gs", extra: 'var DEFAULT_SITE="kr";', fn: "setupNewsTriggers", sheetName: "전송기록",
    triggers: [{ fn: "fetchAITimesAndSendToSlack", type: "CLOCK" }, { fn: "sendAiTimesNews", type: "CLOCK" }, { fn: "sendDailyOther", type: "CLOCK" }, { fn: "sendAiTimesNews", type: "ON_OPEN" }] }),
  // 새 기사 14건: 슬랙에는 최신 10건만, 나머지 4건은 시트에만
  news_overflow: run({ file: "news_aitimes_rss.gs", extra: 'var DEFAULT_SITE="kr";', fn: "sendAiTimesNews", props: PROD, sheetName: "전송기록", rssCount: 14 }),
  news_overflow_second_run: run({ file: "news_aitimes_rss.gs", extra: 'var DEFAULT_SITE="kr";', fn: "sendAiTimesNews", props: { ...PROD, sentArticleIds: JSON.stringify(Array.from({ length: 14 }, (_, k) => String(101 + k))) }, sheetName: "전송기록", rssCount: 14 }),
  swea_sat_test: run({ file: "coding_swea.gs", fn: "sendDailySWEA", props: { ...PROD, ...TEST }, now: SAT, rows: SW, sheetName: "SWEA" }),
};
console.log(JSON.stringify(res));
