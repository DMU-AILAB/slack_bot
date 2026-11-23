"""기사 군집화와 순위화 (상세구현명세서 8.2). 순수 함수라 가짜 임베딩으로 테스트할 수 있다."""
import math
from dataclasses import dataclass

import numpy as np

from src import config


@dataclass
class Cluster:
    members: list[int]          # 입력 인덱스
    n_articles: int
    n_sources: int
    newest_epoch: int
    score: float = 0.0


def cluster_embeddings(emb: np.ndarray, threshold: float = config.CLUSTER_DISTANCE_THRESHOLD) -> list[int]:
    """코사인 거리 기준 응집 군집화. 2건 미만이면 각자 하나의 군집."""
    n = len(emb)
    if n < 2:
        return list(range(n))
    from sklearn.cluster import AgglomerativeClustering
    model = AgglomerativeClustering(n_clusters=None, distance_threshold=threshold, metric="cosine", linkage="average")
    return [int(x) for x in model.fit_predict(emb)]


def rank_clusters(labels: list[int], metas: list[dict], now_epoch: float, top_n: int) -> list[Cluster]:
    """점수 = 0.5*기사 수 + 0.3*매체 수 + 0.2*최신성. GeekNews가 수로 독식하지 않도록 기사 수는 로그로 완만하게."""
    groups: dict[int, list[int]] = {}
    for i, lb in enumerate(labels):
        groups.setdefault(lb, []).append(i)
    max_n = max((len(v) for v in groups.values()), default=1)
    out = []
    for members in groups.values():
        sources = {metas[i].get("source_name", "") for i in members}
        newest = max(int(metas[i].get("published_epoch", 0)) for i in members)
        days = max(0.0, (now_epoch - newest) / 86400)
        count_n = math.log1p(len(members)) / math.log1p(max_n)
        source_n = min(len(sources), 3) / 3
        score = 0.5 * count_n + 0.3 * source_n + 0.2 * math.exp(-days / 3)
        out.append(Cluster(members, len(members), len(sources), newest, score))
    out.sort(key=lambda c: (-c.score, -c.newest_epoch))
    return out[:top_n]


def pick_representatives(cluster: Cluster, metas: list[dict], k: int = config.SUMMARY_ARTICLES_PER_CLUSTER) -> list[int]:
    """최신순이되 서로 다른 매체를 먼저 고른다."""
    order = sorted(cluster.members, key=lambda i: -int(metas[i].get("published_epoch", 0)))
    picked, seen = [], set()
    for i in order:
        src = metas[i].get("source_name", "")
        if src not in seen:
            picked.append(i)
            seen.add(src)
    for i in order:
        if len(picked) >= k:
            break
        if i not in picked:
            picked.append(i)
    return picked[:k]
