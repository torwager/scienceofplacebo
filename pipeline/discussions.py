"""Export GitHub Discussions (topics, counts, last activity, first lines) to data/discussions.json for the board page.
Needs a token with read access to discussions: GITHUB_TOKEN in Actions, or `gh auth token` locally."""
import json, os, re, subprocess, time, requests
from . import config

REPO = ("torwager", "scienceofplacebo")
Q = """query($owner:String!,$name:String!,$after:String){ repository(owner:$owner,name:$name){
  discussions(first:50, after:$after, orderBy:{field:UPDATED_AT, direction:DESC}){
    pageInfo{hasNextPage endCursor}
    nodes{ number title url createdAt updatedAt bodyText category{name} author{login avatarUrl}
      comments(last:1){ totalCount nodes{ author{login} createdAt bodyText } } } } } }"""


def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def main():
    t = token()
    if not t:
        print("no GitHub token; skipping discussions export"); return
    items, after = [], None
    while True:
        r = requests.post("https://api.github.com/graphql", json={"query": Q, "variables": {"owner": REPO[0], "name": REPO[1], "after": after}},
                          headers={"Authorization": f"bearer {t}", "User-Agent": config.TOOL_NAME}, timeout=60)
        r.raise_for_status()
        d = r.json()["data"]["repository"]["discussions"]
        for n in d["nodes"]:
            last = (n["comments"]["nodes"] or [None])[0]
            body = re.sub(r"\s+", " ", n.get("bodyText") or "").strip()
            items.append({"number": n["number"], "title": n["title"], "url": n["url"], "category": (n.get("category") or {}).get("name"),
                          "author": (n.get("author") or {}).get("login"), "created": n["createdAt"][:10], "updated": n["updatedAt"][:16].replace("T", " "),
                          "comments": n["comments"]["totalCount"], "excerpt": body[:240],
                          "last": {"author": (last.get("author") or {}).get("login"), "date": last["createdAt"][:10], "text": re.sub(r"\s+", " ", last.get("bodyText") or "")[:160]} if last else None,
                          "paper_id": n["title"] if n["title"].startswith(("doi:", "pmid:", "title:")) else None})
        if not d["pageInfo"]["hasNextPage"]:
            break
        after = d["pageInfo"]["endCursor"]
    out = config.DATA / "discussions.json"
    json.dump({"updated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "threads": items}, open(out, "w"), indent=1, ensure_ascii=False)
    print(f"discussions: {len(items)} threads -> {out}")


if __name__ == "__main__":
    main()
