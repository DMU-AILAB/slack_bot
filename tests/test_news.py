import math
from datetime import date

import numpy as np

from src.news import cluster as cl
from src.news.window import analyze, parse_count, parse_window

TODAY = date(2026, 11, 21)  # 토요일


def test_window_parsing():
    assert parse_window("최근 3일 소식", TODAY)[:2] == (date(2026, 11, 19), TODAY)
    assert parse_window("이번 주 이슈", TODAY)[0] == date(2026, 11, 16)
    assert parse_window("지난주 소식", TODAY)[:2] == (date(2026, 11, 9), date(2026, 11, 15))
    assert parse_window("어제 소식 요약해줘", TODAY)[:2] == (date(2026, 11, 20), date(2026, 11, 20))
    assert parse_window("최근 이슈", TODAY)[0] == date(2026, 11, 15)      # 기본 7일


def test_count_parsing_and_cap():
    assert parse_count("이슈 3가지") == 3 and parse_count("이슈 5개") == 5
    assert parse_count("세 가지만") == 3 and parse_count("두 개") == 2
    assert parse_count("이슈 9가지") == 5 and parse_count("이슈 정리") == 3


def test_query_kind():
    assert analyze("최근 가장 중요한 이슈 3가지만 정리해줘", TODAY).kind == "issues"
    assert analyze("어제 소식 요약해줘", TODAY).kind == "issues"
    q = analyze("RAG 관련 최근 소식", TODAY)
    assert q.kind == "topic" and "RAG" in q.topic
    assert analyze("OpenAI 동향", TODAY).kind == "topic"


def test_cluster_ranking_prefers_more_articles_sources_and_recency():
    # 군집 A: 3건, 두 매체 / 군집 B: 1건
    a = np.array([[1, 0, 0], [0.98, 0.05, 0], [0.97, 0.04, 0.02], [0, 1, 0]], dtype=float)
    labels = cl.cluster_embeddings(a, threshold=0.2)
    assert labels[0] == labels[1] == labels[2] != labels[3]
    now = 1_000_000.0
    metas = [{"source_name": "GeekNews", "published_epoch": now - 3600},
             {"source_name": "AI TIMES", "published_epoch": now - 7200},
             {"source_name": "GeekNews", "published_epoch": now - 9000},
             {"source_name": "GeekNews", "published_epoch": now - 100}]
    top = cl.rank_clusters(labels, metas, now, 2)
    assert top[0].n_articles == 3 and top[0].n_sources == 2
    assert top[1].n_articles == 1                      # 1건 군집은 뒤로
    assert top[0].score > top[1].score and math.isfinite(top[0].score)


def test_single_doc_and_representatives():
    assert cl.cluster_embeddings(np.array([[1.0, 0.0]])) == [0]
    metas = [{"source_name": "A", "published_epoch": 5}, {"source_name": "A", "published_epoch": 9},
             {"source_name": "B", "published_epoch": 1}]
    c = cl.Cluster([0, 1, 2], 3, 2, 9)
    picked = cl.pick_representatives(c, metas, 2)
    assert {metas[i]["source_name"] for i in picked} == {"A", "B"}   # 서로 다른 매체 우선
