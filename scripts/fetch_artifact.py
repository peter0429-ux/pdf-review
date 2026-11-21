"""下载 GitHub Actions artifact。

坑：gh api .../artifacts/<id>/zip 会 302 到 Azure Blob 签名 URL，
第二跳不能再带 Authorization 头，否则 403 "Server failed to authenticate"。
所以第一跳用 NoRedirect 拿到 Location，第二跳裸 urlopen。
"""

import json
import subprocess
import sys
import urllib.request

REPO = "peter0429-ux/pdf-review"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def gh_token():
    out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def locate(artifact_id):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip",
        headers={"Authorization": f"Bearer {gh_token()}", "Accept": "application/vnd.github+json"},
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(req)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.headers["Location"]
        raise
    raise RuntimeError("没有拿到重定向")


def download(artifact_id, dest):
    url = locate(artifact_id)
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


if __name__ == "__main__":
    artifact_id, dest = sys.argv[1], sys.argv[2]
    download(artifact_id, dest)
    import os
    print(f"已下载 {dest}（{os.path.getsize(dest)} 字节）")
