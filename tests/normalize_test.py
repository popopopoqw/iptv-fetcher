from iptv_fetcher.models import Entry
from iptv_fetcher.normalize import build_candidates, classify, normalize_name


def test_normalize_cctv_variants():
    assert normalize_name("CCTV-1 综合") == "cctv1"
    assert normalize_name("CCTV1") == "cctv1"
    assert normalize_name("cctv 5+") == "cctv5+"
    assert normalize_name("CCTV5+") == "cctv5+"
    assert normalize_name("CCTV-5+ 体育") == "cctv5+"


def test_normalize_strips_tags():
    assert normalize_name("湖南卫视 (1080p)") == "湖南卫视"
    assert normalize_name("CCTV-3 [Not 24/7]") == "cctv3"
    assert normalize_name("东方卫视 高清") == "东方卫视"


def test_normalize_keeps_distinct_channels():
    assert normalize_name("CCTV-1") != normalize_name("CCTV-2")
    assert normalize_name("广东体育") == "广东体育"


def test_classify_regions():
    def e(name, hint="cn", country=""):
        return Entry(name=name, url="http://x/y", source="t",
                     region_hint=hint, tvg_country=country)

    assert classify(e("CCTV-1 综合"))[0] == "cn-cctv"
    assert classify(e("湖南卫视"))[0] == "cn-satellite"
    assert classify(e("凤凰中文台"))[0] == "cn-hmt"
    assert classify(e("中天新闻"))[0] == "cn-hmt"
    assert classify(e("杭州综合频道"))[0] == "cn-local"
    assert classify(e("CNN", hint="foreign"))[0] == "foreign"
    assert classify(e("NHK", hint="foreign", country="jp")) == ("foreign", "Jp")
    assert classify(e("Some TV", hint="cn", country="US")) == ("foreign", "Us")


def test_build_candidates_dedup_and_cap():
    entries = [
        Entry("CCTV-1", "http://a/1", "s1"),
        Entry("CCTV1", "http://b/1", "s2"),
        Entry("cctv-1", "http://c/1", "s1"),
        Entry("CCTV1", "http://d/1", "s1"),
        Entry("CCTV1", "http://e/1", "s3"),
    ]
    # 默认 0 = 不限制：全部候选保留，来源分散化排序
    cands = build_candidates(entries)
    assert all(c.key == "cctv1" for c in cands)
    assert len(cands) == 5
    assert cands[0].entry.source != cands[1].entry.source  # 前两个来自不同源
    # 显式设上限仍生效
    capped = build_candidates(entries, candidates_per_channel=2)
    assert len(capped) == 2
    assert {c.entry.source for c in capped} == {"s1", "s2"}
