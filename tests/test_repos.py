from datetime import date

from aidec import repos

TODAY = date(2027, 11, 13)


def proj(slug, last, issues):
    return {"slug": slug, "last_activity": last, "issues": issues}


def iss(open_, oldest=None, plans=(), fetched="2027-11-13T08:00:00+09:00"):
    return {"fetched_at": fetched, "open": open_, "oldest_open_at": oldest, "plans": list(plans)}


def test_lists_open_or_recent_newest_first_and_skips_the_rest():
    doc = {"projects": [
        proj("github.com/a/old-quiet", "2027-01-01T00:00:00+09:00", iss(0)),
        proj("github.com/a/old-busy", "2027-01-01T00:00:00+09:00", iss(80, "2026-06-02T01:11:00+00:00")),
        proj("github.com/a/recent", "2027-11-12T10:00:00+09:00", iss(0)),
        proj("github.com/a/no-github", "2027-11-13T10:00:00+09:00", None),
    ]}
    assert repos.format_repos(doc, TODAY) == (
        ["- recent  Open 0"],
        ["- old-busy  Open 80  Oldest 2026-06-02  Latest 2027-01-01"],
    )


def test_plans_and_missing_plan_and_stale_fetch():
    doc = {"projects": [proj("github.com/a/kit", "2027-11-13T10:00:00+09:00", iss(
        2, "2027-10-01T00:00:00+00:00",
        [{"issue": 34, "path": "p.md", "done": 3, "total": 10},
         {"issue": 51, "path": "gone.md", "done": None, "total": None}],
        fetched="2027-11-10T08:00:00+09:00"))]}
    assert repos.format_repos(doc, TODAY) == ([
        "- kit  Open 2  Oldest 2027-10-01  #34 3/10  #51 no plan  (as of 2027-11-10)"], [])


def test_without_sr_the_section_is_absent():
    assert repos.repos_section(TODAY) is None
