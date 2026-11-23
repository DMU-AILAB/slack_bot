"""웹 검색 provider (수상작 분석 전용, 상세구현명세서 8.1.1). naver | searxng 를 같은 형식으로 맞춘다.

검색어에는 공모전 이름·분야만 넣고 슬랙 내용이나 사용자 정보는 넣지 않는다. API 키는 로그에 남기지 않는다.
"""
import hashlib
import html
import logging
import re
from dataclasses import dataclass

import requests

from src import config
from src.sources import web

log = logging.getLogger(__name__)


class SearchUnavailable(RuntimeError):
    """키가 없거나 검색 서비스가 응답하지 않음."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    published: str = ""


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _naver(query: str, top_k: int) -> list[SearchResult]:
    cid, sec = config.env("NAVER_CLIENT_ID"), config.env("NAVER_CLIENT_SECRET")
    if not cid or not sec:
        raise SearchUnavailable("NAVER 검색 API 키가 없습니다")
    out: list[SearchResult] = []
    for kind in ("webkr", "blog", "news"):
        r = requests.get(f"https://openapi.naver.com/v1/search/{kind}.json", params={"query": query, "display": top_k},
                         headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec}, timeout=config.HTTP_TIMEOUT_SEC)
        if r.status_code != 200:
            log.warning("Naver 검색 실패: HTTP %s (%s)", r.status_code, kind)
            if r.status_code in (401, 403, 429):
                raise SearchUnavailable(f"HTTP {r.status_code}")
            continue
        for it in r.json().get("items", []):
            out.append(SearchResult(_strip(it.get("title")), it.get("link", ""), _strip(it.get("description")),
                                    it.get("postdate") or it.get("pubDate", "")))
    return out[: top_k * 2]


def _searxng(query: str, top_k: int) -> list[SearchResult]:
    base = config.env("SEARXNG_URL")
    if not base:
        raise SearchUnavailable("SEARXNG_URL이 없습니다")
    r = requests.get(base.rstrip("/") + "/search", params={"q": query, "format": "json", "language": "ko-KR"},
                     timeout=config.HTTP_TIMEOUT_SEC)
    if r.status_code != 200:
        raise SearchUnavailable(f"HTTP {r.status_code}")
    return [SearchResult(_strip(x.get("title")), x.get("url", ""), _strip(x.get("content")), x.get("publishedDate") or "")
            for x in r.json().get("results", [])[:top_k]]


def search(query: str, top_k: int = config.SEARCH_TOP_K) -> list[SearchResult]:
    key = hashlib.sha1(f"{config.SEARCH_PROVIDER}:{query}:{top_k}".encode()).hexdigest()
    hit = web.cache_get("search", key, config.SEARCH_CACHE_HOURS)
    if hit is not None:
        return [SearchResult(**x) for x in hit]
    try:
        provider = {"naver": _naver, "searxng": _searxng}[config.SEARCH_PROVIDER]
    except KeyError:
        raise SearchUnavailable("알 수 없는 SEARCH_PROVIDER")
    try:
        res = provider(query, top_k)
    except requests.RequestException as e:
        raise SearchUnavailable(type(e).__name__) from e
    web.cache_put("search", key, [r.__dict__ for r in res])
    return res
