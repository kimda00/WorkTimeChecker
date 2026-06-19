# -*- coding: utf-8 -*-
"""Generate beginner-to-practitioner DevOps learning HTML documents.

The generated files are intended for local reading in a browser and printing to
PDF. They are self-contained: CSS, diagrams, examples, and exercises are inside
each HTML file.
"""

from __future__ import annotations

import html
import os
from pathlib import Path
from textwrap import dedent


GENERATED_AT = "2026-06-12"


SOURCES = {
    "Docker": [
        ("Docker overview", "https://docs.docker.com/get-started/docker-overview/"),
        ("Dockerfile best practices", "https://docs.docker.com/build/building/best-practices/"),
        ("Docker Compose", "https://docs.docker.com/compose/"),
    ],
    "Jenkins": [
        ("Jenkins user handbook", "https://www.jenkins.io/doc/book/"),
        ("Jenkins Pipeline", "https://www.jenkins.io/doc/book/pipeline/"),
        ("Jenkins on Docker", "https://www.jenkins.io/doc/book/installing/docker/"),
    ],
    "Kubernetes": [
        ("Kubernetes overview", "https://kubernetes.io/docs/concepts/overview/"),
        ("Kubernetes Deployments", "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/"),
        ("Kubernetes Services", "https://kubernetes.io/docs/concepts/services-networking/service/"),
        ("Kubernetes ConfigMaps", "https://kubernetes.io/docs/concepts/configuration/configmap/"),
        ("Kubernetes Secrets", "https://kubernetes.io/docs/concepts/configuration/secret/"),
        ("Kubernetes Persistent Volumes", "https://kubernetes.io/docs/concepts/storage/persistent-volumes/"),
    ],
}


STYLE = r"""
:root {
  --bg: #f7f9fc;
  --paper: #ffffff;
  --ink: #172033;
  --muted: #5c677d;
  --line: #d9e0ec;
  --brand: #2563eb;
  --brand2: #0f766e;
  --warn: #b45309;
  --bad: #b91c1c;
  --good: #047857;
  --code: #0f172a;
  --soft: #eef4ff;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Malgun Gothic", "Apple SD Gothic Neo", Segoe UI, Arial, sans-serif;
  line-height: 1.72;
}
a { color: var(--brand); text-decoration: none; }
a:hover { text-decoration: underline; }
.layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); min-height: 100vh; }
nav {
  position: sticky; top: 0; height: 100vh; overflow: auto;
  padding: 24px 18px; background: #101827; color: #e5edf7;
  border-right: 1px solid #0b1220;
}
nav h2 { margin: 0 0 8px; font-size: 20px; }
nav .sub { color: #9fb1cd; font-size: 12px; margin-bottom: 18px; }
nav a { display: block; color: #dce7f7; padding: 7px 8px; border-radius: 8px; font-size: 13px; }
nav a:hover { background: rgba(255,255,255,.08); text-decoration: none; }
main { padding: 34px min(5vw, 64px) 80px; }
.hero, .chapter, .appendix {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 28px;
  margin: 0 0 22px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, .06);
}
.hero { padding: 38px; background: linear-gradient(135deg, #ffffff 0%, #eef4ff 100%); }
h1 { margin: 0 0 10px; font-size: 34px; line-height: 1.18; letter-spacing: -0.2px; }
h2 { margin: 0 0 14px; font-size: 25px; line-height: 1.28; }
h3 { margin: 24px 0 8px; font-size: 18px; }
p { margin: 8px 0 12px; }
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px;
  background: #e0f2fe; color: #075985; font-weight: 800; font-size: 12px;
}
.grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 14px; }
.tri { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 14px; }
.card {
  border: 1px solid var(--line); border-radius: 12px; padding: 15px;
  background: #fbfdff;
}
.card strong { display: block; margin-bottom: 5px; }
.note, .warn, .practice, .mistake {
  border-radius: 12px; padding: 14px 16px; margin: 14px 0;
  border: 1px solid var(--line);
}
.note { background: #f0f9ff; border-color: #bae6fd; }
.warn { background: #fffbeb; border-color: #fde68a; }
.practice { background: #ecfdf5; border-color: #a7f3d0; }
.mistake { background: #fef2f2; border-color: #fecaca; }
.label { font-weight: 900; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
pre {
  margin: 12px 0; padding: 16px;
  overflow: auto; border-radius: 12px;
  background: var(--code); color: #e5e7eb;
  line-height: 1.45; font-size: 13px;
}
code { font-family: Consolas, "Cascadia Mono", monospace; }
p code, li code { background: #eef2ff; color: #1e3a8a; padding: 2px 5px; border-radius: 6px; }
table { width: 100%; border-collapse: collapse; margin: 14px 0; }
th, td { border: 1px solid var(--line); padding: 9px 10px; vertical-align: top; }
th { background: #f1f5f9; text-align: left; }
.diagram {
  margin: 16px 0; padding: 16px; border: 1px solid var(--line);
  border-radius: 14px; background: #f8fbff; overflow: auto;
}
.flow { display: flex; align-items: stretch; gap: 10px; flex-wrap: wrap; }
.node {
  min-width: 128px; flex: 1; padding: 13px 12px; border-radius: 12px;
  border: 1px solid #bfdbfe; background: #eff6ff; text-align: center; font-weight: 800;
}
.arrow { display: flex; align-items: center; color: var(--brand); font-weight: 900; font-size: 24px; }
.layers { display: grid; gap: 8px; max-width: 720px; }
.layer { border: 1px solid #c7d2fe; background: #eef2ff; border-radius: 9px; padding: 9px 12px; }
.layer:nth-child(2n) { background: #ecfeff; border-color: #a5f3fc; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: start; }
.toc-block { columns: 2; column-gap: 28px; }
.toc-block a { display: block; break-inside: avoid; padding: 3px 0; }
.level {
  display: inline-block; min-width: 72px; text-align: center; border-radius: 999px;
  padding: 3px 9px; font-weight: 900; font-size: 12px; color: #fff; background: var(--brand2);
}
.level.beginner { background: #2563eb; }
.level.basic { background: #0891b2; }
.level.intermediate { background: #0f766e; }
.level.practical { background: #7c3aed; }
.level.advanced { background: #be123c; }
.pagehint { color: var(--muted); font-size: 12px; }
@media print {
  body { background: #fff; }
  .layout { display: block; }
  nav { display: none; }
  main { padding: 0; }
  .hero, .chapter, .appendix { box-shadow: none; border-radius: 0; page-break-after: always; margin: 0; border: 0; }
  pre { white-space: pre-wrap; }
}
@media (max-width: 900px) {
  .layout { display: block; }
  nav { position: relative; height: auto; }
  .grid, .tri, .split { grid-template-columns: 1fr; }
  main { padding: 18px; }
}
"""


LEVEL_LABELS = {
    "beginner": "입문",
    "basic": "초급",
    "intermediate": "중급",
    "practical": "실무",
    "advanced": "심화",
}


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def flow(nodes: list[str]) -> str:
    parts: list[str] = ['<div class="diagram"><div class="flow">']
    for i, node in enumerate(nodes):
        if i:
            parts.append('<div class="arrow">→</div>')
        parts.append(f'<div class="node">{esc(node)}</div>')
    parts.append("</div></div>")
    return "".join(parts)


def layers(items: list[str]) -> str:
    body = "".join(f'<div class="layer">{esc(item)}</div>' for item in items)
    return f'<div class="diagram"><div class="layers">{body}</div></div>'


def cards(items: list[tuple[str, str]]) -> str:
    body = "".join(
        f'<div class="card"><strong>{esc(title)}</strong><p>{esc(text)}</p></div>'
        for title, text in items
    )
    return f'<div class="grid">{body}</div>'


def code_block(code: str, lang: str = "") -> str:
    return f"<pre><code>{esc(dedent(code).strip())}</code></pre>"


def list_items(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def chapter_html(index: int, chapter: dict) -> str:
    level = chapter["level"]
    html_parts = [
        f'<section class="chapter" id="ch{index:02d}">',
        f'<span class="level {level}">{LEVEL_LABELS[level]}</span>',
        f"<h2>{index}. {esc(chapter['title'])}</h2>",
        f"<p>{esc(chapter['intro'])}</p>",
    ]
    if chapter.get("flow"):
        html_parts.append(flow(chapter["flow"]))
    if chapter.get("layers"):
        html_parts.append(layers(chapter["layers"]))
    html_parts.append("<h3>바텀업 이해</h3>")
    html_parts.append(list_items(chapter["bottom_up"]))
    html_parts.append("<h3>실무에서 보는 관점</h3>")
    html_parts.append(cards(chapter["practical"]))
    if chapter.get("code"):
        html_parts.append("<h3>예시 코드</h3>")
        html_parts.append(code_block(chapter["code"]))
    html_parts.append('<div class="mistake"><div class="label">자주 하는 실수</div>')
    html_parts.append(list_items(chapter["mistakes"]))
    html_parts.append("</div>")
    html_parts.append('<div class="practice"><div class="label">손으로 해볼 실습</div>')
    html_parts.append(list_items(chapter["practice"]))
    html_parts.append("</div>")
    html_parts.append('<div class="note"><div class="label">스스로 점검</div>')
    html_parts.append(list_items(chapter["checks"]))
    html_parts.append("</div>")
    html_parts.append("</section>")
    return "\n".join(html_parts)


def render_doc(title: str, subtitle: str, chapters: list[dict], sources: list[tuple[str, str]], out: Path) -> None:
    nav_links = "\n".join(
        f'<a href="#ch{i:02d}">{i}. {esc(ch["title"])}</a>' for i, ch in enumerate(chapters, 1)
    )
    toc_links = "\n".join(
        f'<a href="#ch{i:02d}">{i}. {esc(ch["title"])} <span class="pagehint">({LEVEL_LABELS[ch["level"]]})</span></a>'
        for i, ch in enumerate(chapters, 1)
    )
    source_items = "".join(f'<li><a href="{esc(url)}">{esc(name)}</a></li>' for name, url in sources)
    body = "\n".join(chapter_html(i, ch) for i, ch in enumerate(chapters, 1))
    document = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>{STYLE}</style>
</head>
<body>
<div class="layout">
  <nav>
    <h2>{esc(title)}</h2>
    <div class="sub">생성일 {GENERATED_AT}<br>초보자부터 실무자까지</div>
    {nav_links}
    <a href="#appendix">부록과 공식 문서</a>
  </nav>
  <main>
    <section class="hero">
      <span class="badge">Bottom-up Learning Pack</span>
      <h1>{esc(title)}</h1>
      <p>{esc(subtitle)}</p>
      <div class="split">
        <div>
          <h3>읽는 방법</h3>
          <p>각 장은 작은 원리에서 시작해서 실제 운영 판단으로 올라갑니다. 명령어를 외우기보다 어떤 문제가 생겼을 때 어느 계층을 의심해야 하는지를 익히는 흐름입니다.</p>
        </div>
        <div>
          <h3>목차</h3>
          <div class="toc-block">{toc_links}</div>
        </div>
      </div>
    </section>
    {body}
    <section class="appendix" id="appendix">
      <h2>부록. 공식 문서와 다음 학습 순서</h2>
      <p>이 문서는 아래 공식 문서를 기준으로 개념을 재구성했습니다. 실제 설치 명령, 버전 정책, 세부 플래그는 시간이 지나며 바뀔 수 있으므로 운영 적용 전 공식 문서를 확인하세요.</p>
      <ul>{source_items}</ul>
      <div class="warn"><div class="label">운영 주의</div><p>실무 환경에서는 보안, 네트워크, 권한, 백업, 장애 대응 절차가 조직마다 다릅니다. 이 교재의 예시는 학습용 기본형이며, 운영 반영 전 조직 표준과 함께 검토해야 합니다.</p></div>
    </section>
  </main>
</div>
</body>
</html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")


def base_chapter(level: str, title: str, intro: str, flow_nodes: list[str], bottom: list[str],
                 practical: list[tuple[str, str]], code: str, mistakes: list[str],
                 practice: list[str], checks: list[str], layer_items: list[str] | None = None) -> dict:
    return {
        "level": level,
        "title": title,
        "intro": intro,
        "flow": flow_nodes,
        "layers": layer_items,
        "bottom_up": bottom,
        "practical": practical,
        "code": code,
        "mistakes": mistakes,
        "practice": practice,
        "checks": checks,
    }


DOCKER = [
    base_chapter(
        "beginner", "컨테이너가 필요한 이유",
        "컨테이너는 애플리케이션과 실행 환경을 하나의 이동 가능한 단위로 묶는 방법입니다.",
        ["내 노트북", "이미지", "컨테이너", "테스트 서버", "운영 서버"],
        [
            "프로그램은 코드만으로 실행되지 않습니다. 런타임, 라이브러리, 환경변수, 파일 경로, 포트가 함께 맞아야 합니다.",
            "컨테이너는 이 실행 조건을 이미지에 기록하고, 이미지를 실행한 인스턴스를 컨테이너로 만듭니다.",
            "가상머신은 운영체제 전체를 띄우는 느낌이고, 컨테이너는 호스트 커널을 공유하면서 프로세스를 격리합니다.",
            "초보자는 컨테이너를 작은 컴퓨터로 이해해도 되지만, 실무자는 격리된 프로세스와 파일시스템으로 이해해야 합니다.",
        ],
        [
            ("일관성", "개발, 테스트, 운영에서 같은 이미지를 실행하면 환경 차이로 생기는 버그를 줄일 수 있습니다."),
            ("배포 단위", "컨테이너 이미지는 배포 가능한 산출물입니다. CI가 이미지를 만들고 CD가 그 이미지를 배포합니다."),
            ("한계", "컨테이너가 모든 문제를 해결하지는 않습니다. 네트워크, 영속 데이터, 권한, 커널 의존성은 여전히 설계해야 합니다."),
            ("운영 감각", "컨테이너는 삭제될 수 있다는 전제를 깔고 로그, 설정, 데이터 위치를 외부화해야 합니다."),
        ],
        "docker run --rm hello-world",
        [
            "컨테이너를 영구 서버처럼 생각해서 컨테이너 내부에 중요한 데이터를 저장하는 실수",
            "이미지와 컨테이너를 같은 것으로 부르는 실수",
            "호스트에서 되는 명령이 컨테이너 안에서도 당연히 된다고 생각하는 실수",
        ],
        [
            "`docker run --rm hello-world`를 실행하고, 출력이 어떤 단계로 흘러가는지 적어보세요.",
            "`docker ps -a`로 종료된 컨테이너가 남는지 확인해보세요.",
            "컨테이너가 삭제되어도 이미지가 남는다는 점을 `docker images`로 확인하세요.",
        ],
        [
            "이미지와 컨테이너의 차이를 한 문장으로 설명할 수 있는가?",
            "컨테이너 내부 파일이 사라질 수 있는 이유를 설명할 수 있는가?",
            "컨테이너가 가상머신보다 가벼운 이유를 말할 수 있는가?",
        ],
    ),
    base_chapter(
        "beginner", "이미지, 레이어, 컨테이너",
        "Docker 이미지는 여러 읽기 전용 레이어의 조합이고, 컨테이너는 그 위에 쓰기 가능한 레이어를 얹은 실행 상태입니다.",
        ["Base image", "Dockerfile instruction", "Image layers", "Writable container layer"],
        [
            "Dockerfile의 각 명령은 보통 새 레이어를 만듭니다.",
            "이미지 레이어는 재사용됩니다. 그래서 같은 베이스 이미지를 쓰는 컨테이너 여러 개가 빠르게 생성됩니다.",
            "컨테이너에서 파일을 수정하면 이미지가 바뀌는 것이 아니라 컨테이너 전용 쓰기 레이어가 바뀝니다.",
            "이미지를 새로 빌드할 때 변경되지 않은 레이어는 캐시로 재사용될 수 있습니다.",
        ],
        [
            ("캐시 전략", "자주 바뀌는 파일은 Dockerfile 뒤쪽에 배치하면 빌드 캐시 효율이 좋아집니다."),
            ("크기 관리", "불필요한 패키지와 빌드 산출물을 최종 이미지에 남기지 않는 것이 중요합니다."),
            ("불변성", "운영에서는 컨테이너에 접속해 수정하기보다 이미지를 새로 빌드해 배포합니다."),
            ("추적성", "이미지 태그와 digest를 기록하면 어떤 코드가 배포됐는지 추적할 수 있습니다."),
        ],
        """
        docker image inspect nginx:alpine
        docker run --name web -d nginx:alpine
        docker exec web sh -c "echo hello > /usr/share/nginx/html/hello.txt"
        docker rm -f web
        """,
        [
            "`latest` 태그만 믿고 언제 어떤 이미지가 배포됐는지 모르는 상태",
            "컨테이너 내부 수정으로 운영 패치를 하는 습관",
            "레이어 캐시를 깨뜨리는 Dockerfile 순서",
        ],
        [
            "작은 파일 하나를 추가하는 Dockerfile을 만들고 `docker history`로 레이어를 확인하세요.",
            "같은 이미지를 두 번 실행했을 때 컨테이너 ID가 다른 것을 확인하세요.",
            "컨테이너 안에서 만든 파일이 컨테이너 삭제 후 사라지는지 확인하세요.",
        ],
        [
            "왜 이미지는 읽기 전용이어야 운영이 안정적인가?",
            "왜 Dockerfile 순서가 빌드 속도에 영향을 주는가?",
            "컨테이너를 재시작하는 것과 이미지를 재빌드하는 것은 어떻게 다른가?",
        ],
        ["FROM node:22-alpine", "WORKDIR /app", "COPY package*.json ./", "RUN npm ci", "COPY . .", "CMD node server.js"],
    ),
    base_chapter(
        "basic", "Dockerfile 작성법",
        "Dockerfile은 이미지를 만드는 조리법입니다. 운영 수준에서는 작동만이 아니라 재현성, 크기, 보안까지 고려해야 합니다.",
        ["소스 코드", "Dockerfile", "docker build", "이미지", "컨테이너 실행"],
        [
            "`FROM`은 출발점입니다. 런타임이 포함된 공식 이미지를 고르면 시작이 쉽습니다.",
            "`WORKDIR`은 이후 명령이 실행될 기본 폴더를 만듭니다.",
            "`COPY`는 호스트 파일을 이미지 안으로 복사합니다. `.dockerignore`로 불필요한 파일을 제외해야 합니다.",
            "`RUN`은 빌드 시점에 실행되고, `CMD`는 컨테이너 실행 시 기본 명령입니다.",
        ],
        [
            ("멀티 스테이지", "빌드 도구가 필요한 단계와 실제 실행 단계를 분리해 최종 이미지를 작게 만듭니다."),
            ("고정 버전", "베이스 이미지와 패키지 버전을 명확히 하면 재현성이 좋아집니다."),
            ("비루트 실행", "운영 컨테이너는 가능한 일반 사용자로 실행합니다."),
            ("빌드 컨텍스트", "소스 전체가 Docker daemon으로 전송되므로 큰 파일을 제외해야 합니다."),
        ],
        """
        FROM node:22-alpine AS deps
        WORKDIR /app
        COPY package*.json ./
        RUN npm ci

        FROM node:22-alpine
        WORKDIR /app
        ENV NODE_ENV=production
        COPY --from=deps /app/node_modules ./node_modules
        COPY . .
        USER node
        EXPOSE 3000
        CMD ["node", "server.js"]
        """,
        [
            "소스보다 `package.json`을 늦게 복사해서 매 빌드마다 의존성을 다시 설치하는 실수",
            "빌드에 필요한 비밀값을 `ARG`나 `ENV`로 이미지에 남기는 실수",
            "컨테이너에서 root 권한으로 애플리케이션을 실행하는 실수",
        ],
        [
            "간단한 Node, Python, Java 앱 중 하나를 골라 Dockerfile을 작성해보세요.",
            "`.dockerignore`에 `.git`, `node_modules`, `dist`, 로그 파일을 넣어보세요.",
            "멀티 스테이지 전후 이미지 크기를 비교하세요.",
        ],
        [
            "`RUN`과 `CMD`의 실행 시점 차이를 설명할 수 있는가?",
            "멀티 스테이지 빌드가 최종 이미지 크기를 줄이는 이유는 무엇인가?",
            "이미지에 비밀값을 넣으면 왜 위험한가?",
        ],
    ),
    base_chapter(
        "basic", "컨테이너 실행, 포트, 환경변수",
        "컨테이너를 실행하려면 이미지뿐 아니라 포트, 환경변수, 이름, 재시작 정책 같은 런타임 설정이 필요합니다.",
        ["docker run", "환경변수", "포트 매핑", "프로세스", "로그"],
        [
            "컨테이너 내부 포트와 호스트 포트는 다릅니다. `-p 8080:80`은 호스트 8080을 컨테이너 80에 연결합니다.",
            "환경변수는 이미지에 고정하지 않고 실행 시점에 주입하는 대표 설정 방식입니다.",
            "컨테이너의 메인 프로세스가 종료되면 컨테이너도 종료됩니다.",
            "로그는 보통 표준출력과 표준에러로 남기고 `docker logs`로 확인합니다.",
        ],
        [
            ("12-Factor", "설정은 코드와 분리하고 환경변수나 외부 설정으로 주입하는 방식이 흔합니다."),
            ("상태 확인", "운영에서는 컨테이너가 떠 있는지보다 요청을 처리할 수 있는지가 중요합니다."),
            ("재시작 정책", "단일 Docker 운영에서는 `--restart unless-stopped` 같은 정책을 이해해야 합니다."),
            ("명령 재정의", "디버깅할 때 `docker run image sh`처럼 기본 CMD를 바꿔 실행할 수 있습니다."),
        ],
        """
        docker run -d --name app \\
          -p 8080:3000 \\
          -e NODE_ENV=production \\
          --restart unless-stopped \\
          myapp:1.0.0

        docker logs -f app
        docker exec -it app sh
        """,
        [
            "호스트 포트와 컨테이너 포트를 뒤집어서 이해하는 실수",
            "로그 파일을 컨테이너 내부에만 남기는 실수",
            "환경변수에 민감정보를 평문으로 무분별하게 넣고 노출하는 실수",
        ],
        [
            "nginx 컨테이너를 호스트 8080 포트로 띄우고 브라우저로 확인하세요.",
            "`docker logs`와 `docker exec`를 사용해 실행 중 컨테이너를 관찰하세요.",
            "컨테이너를 중지, 시작, 삭제하면서 상태 변화를 기록하세요.",
        ],
        [
            "`-p 8080:80`에서 왼쪽과 오른쪽은 각각 무엇인가?",
            "컨테이너 로그를 표준출력으로 보내는 이유는 무엇인가?",
            "컨테이너가 종료되는 조건은 무엇인가?",
        ],
    ),
    base_chapter(
        "intermediate", "볼륨과 데이터 영속성",
        "컨테이너는 사라질 수 있으므로 데이터는 컨테이너 바깥에 두어야 합니다. Docker에서는 볼륨과 바인드 마운트가 핵심입니다.",
        ["컨테이너", "마운트 지점", "Docker volume", "호스트 디스크"],
        [
            "컨테이너 파일시스템은 컨테이너 생명주기에 묶입니다.",
            "볼륨은 Docker가 관리하는 영속 저장소입니다.",
            "바인드 마운트는 호스트의 특정 경로를 컨테이너 안에 직접 연결합니다.",
            "개발 환경은 바인드 마운트가 편하고, 운영 데이터는 명시적 볼륨이 더 안전한 경우가 많습니다.",
        ],
        [
            ("백업", "데이터 볼륨은 백업 대상입니다. 컨테이너 백업이 아니라 데이터 백업을 설계해야 합니다."),
            ("권한", "호스트와 컨테이너의 사용자 ID 차이로 파일 권한 문제가 자주 납니다."),
            ("초기화", "DB 컨테이너는 최초 실행과 재실행 동작이 다를 수 있습니다."),
            ("분리", "애플리케이션 코드, 설정, 데이터, 로그를 어디에 둘지 분리해서 생각합니다."),
        ],
        """
        docker volume create pgdata
        docker run -d --name db \\
          -e POSTGRES_PASSWORD=pass \\
          -v pgdata:/var/lib/postgresql/data \\
          postgres:16
        docker volume inspect pgdata
        """,
        [
            "DB 데이터를 컨테이너 내부에만 두고 컨테이너 삭제로 데이터를 잃는 실수",
            "개발용 바인드 마운트 경로를 운영에서도 그대로 쓰는 실수",
            "권한 문제를 무조건 root 실행으로 덮는 실수",
        ],
        [
            "볼륨을 붙인 DB 컨테이너를 삭제 후 다시 만들고 데이터가 남는지 확인하세요.",
            "바인드 마운트로 로컬 HTML 파일을 nginx에 연결해보세요.",
            "볼륨 목록과 사용하지 않는 볼륨 정리 방법을 확인하세요.",
        ],
        [
            "볼륨과 바인드 마운트의 차이는 무엇인가?",
            "운영 DB를 컨테이너로 띄울 때 가장 먼저 설계할 것은 무엇인가?",
            "컨테이너 삭제와 볼륨 삭제는 어떻게 다른가?",
        ],
    ),
    base_chapter(
        "intermediate", "Docker 네트워크",
        "컨테이너끼리 통신하려면 네트워크를 이해해야 합니다. Compose와 Kubernetes로 가도 서비스 발견의 기초가 됩니다.",
        ["컨테이너 A", "Docker network", "컨테이너 B", "외부 클라이언트"],
        [
            "기본 bridge 네트워크에서는 컨테이너가 가상 네트워크에 붙습니다.",
            "사용자 정의 네트워크에서는 컨테이너 이름으로 DNS 해석이 됩니다.",
            "외부에서 접근하려면 포트 publish가 필요합니다.",
            "내부 통신과 외부 노출은 다른 문제입니다.",
        ],
        [
            ("서비스 이름", "Compose에서는 서비스명이 내부 DNS 이름이 됩니다."),
            ("노출 최소화", "DB 같은 내부 서비스는 호스트에 포트를 열지 않아도 됩니다."),
            ("진단", "연결 문제는 DNS, 포트, 바인딩 주소, 방화벽 순서로 확인합니다."),
            ("보안", "같은 네트워크에 붙은 컨테이너는 서로 접근 가능하므로 네트워크를 분리합니다."),
        ],
        """
        docker network create appnet
        docker run -d --name redis --network appnet redis:7
        docker run --rm --network appnet redis:7 redis-cli -h redis ping
        """,
        [
            "컨테이너 내부에서 `localhost`가 호스트를 의미한다고 착각하는 실수",
            "모든 컨테이너 포트를 호스트에 열어두는 실수",
            "DNS 문제와 애플리케이션 문제를 구분하지 못하는 실수",
        ],
        [
            "두 컨테이너를 같은 사용자 정의 네트워크에 붙이고 이름으로 통신해보세요.",
            "포트를 publish하지 않은 서비스가 외부에서 접근되지 않는지 확인하세요.",
            "`docker network inspect`로 네트워크 구성을 확인하세요.",
        ],
        [
            "컨테이너 내부의 `localhost`는 누구를 가리키는가?",
            "내부 통신과 외부 노출의 차이를 설명할 수 있는가?",
            "사용자 정의 네트워크가 기본 bridge보다 편한 점은 무엇인가?",
        ],
    ),
    base_chapter(
        "intermediate", "Docker Compose",
        "Compose는 여러 컨테이너로 이루어진 로컬 또는 소규모 서비스를 하나의 YAML로 정의합니다.",
        ["compose.yaml", "web", "api", "db", "network와 volume"],
        [
            "단일 컨테이너 명령이 길어지면 재현하기 어렵습니다.",
            "Compose 파일은 서비스, 네트워크, 볼륨, 환경변수를 선언형으로 묶습니다.",
            "서비스명은 내부 DNS 이름이 됩니다.",
            "Compose는 Kubernetes와 다르지만, 서비스를 선언한다는 사고방식을 미리 익히게 해줍니다.",
        ],
        [
            ("개발 표준화", "신입 개발자가 `docker compose up` 하나로 환경을 띄울 수 있게 만듭니다."),
            ("의존 서비스", "DB, Redis, 메시지 큐 같은 주변 서비스를 함께 올리기 좋습니다."),
            ("프로필", "테스트, 관찰도구, 부하도구를 profile로 분리할 수 있습니다."),
            ("운영 한계", "대규모 운영과 자동 복구, 롤링 업데이트는 Kubernetes 같은 오케스트레이터가 더 적합합니다."),
        ],
        """
        services:
          app:
            build: .
            ports:
              - "8080:3000"
            environment:
              DATABASE_URL: postgres://app:pass@db:5432/app
            depends_on:
              - db
          db:
            image: postgres:16
            environment:
              POSTGRES_USER: app
              POSTGRES_PASSWORD: pass
            volumes:
              - pgdata:/var/lib/postgresql/data
        volumes:
          pgdata:
        """,
        [
            "`depends_on`을 DB 준비 완료 보장으로 오해하는 실수",
            "개발용 compose에 운영 비밀번호를 커밋하는 실수",
            "서비스 이름과 컨테이너 이름을 불필요하게 고정하는 실수",
        ],
        [
            "간단한 웹 앱과 DB를 Compose로 띄워보세요.",
            "`docker compose logs -f`로 여러 서비스 로그를 함께 보세요.",
            "DB 포트 publish를 제거하고 앱에서만 DB에 접근되는지 확인하세요.",
        ],
        [
            "Compose에서 서비스명은 어떤 역할을 하는가?",
            "`depends_on`의 한계는 무엇인가?",
            "Compose와 Kubernetes의 역할 차이를 설명할 수 있는가?",
        ],
    ),
    base_chapter(
        "practical", "이미지 태그, 레지스트리, 배포 추적",
        "실무에서는 이미지를 어디에 저장하고 어떤 태그로 배포했는지 추적하는 것이 매우 중요합니다.",
        ["CI 빌드", "이미지 태그", "Registry", "배포 환경", "롤백"],
        [
            "레지스트리는 이미지를 저장하고 배포 대상이 가져갈 수 있게 하는 서버입니다.",
            "태그는 사람이 읽기 쉬운 이름이고, digest는 내용 기반 식별자입니다.",
            "운영 배포에는 `latest`보다 Git SHA, 버전, 빌드 번호를 포함한 태그가 안전합니다.",
            "롤백하려면 이전에 정상 동작한 이미지 태그를 알아야 합니다.",
        ],
        [
            ("태그 정책", "`app:1.4.2`, `app:git-a1b2c3d`, `app:20260612.3`처럼 규칙을 정합니다."),
            ("취약점 스캔", "레지스트리나 CI에서 이미지 취약점 스캔을 수행합니다."),
            ("권한", "push 권한과 pull 권한을 분리하고 토큰을 Jenkins Credentials에 넣습니다."),
            ("감사", "어떤 커밋이 어떤 이미지로 어떤 환경에 배포됐는지 남깁니다."),
        ],
        """
        docker build -t registry.example.com/team/app:1.4.2 .
        docker tag registry.example.com/team/app:1.4.2 registry.example.com/team/app:git-a1b2c3d
        docker push registry.example.com/team/app:1.4.2
        docker push registry.example.com/team/app:git-a1b2c3d
        """,
        [
            "운영 배포가 모두 `latest`라서 롤백 기준이 없는 실수",
            "레지스트리 인증 토큰을 코드 저장소에 넣는 실수",
            "이미지 빌드 시점의 소스 커밋을 기록하지 않는 실수",
        ],
        [
            "로컬 이미지에 버전 태그와 Git SHA 태그를 각각 붙여보세요.",
            "이미지 inspect 결과에서 생성 시각과 label을 확인하세요.",
            "Dockerfile에 OCI label을 추가해 소스 URL과 revision을 남겨보세요.",
        ],
        [
            "태그와 digest의 차이는 무엇인가?",
            "왜 운영에서 `latest`가 위험할 수 있는가?",
            "이미지 롤백에 필요한 최소 정보는 무엇인가?",
        ],
    ),
    base_chapter(
        "practical", "Docker 보안 기본기",
        "컨테이너 보안은 이미지 출처, 실행 권한, 민감정보, 네트워크 노출을 함께 다루는 문제입니다.",
        ["신뢰된 이미지", "최소 패키지", "비루트 사용자", "제한된 권한", "관찰과 스캔"],
        [
            "컨테이너는 격리되지만 완전한 보안 경계로만 믿으면 안 됩니다.",
            "베이스 이미지는 작고 관리가 활발한 공식 이미지를 우선 검토합니다.",
            "root 실행, Docker socket 마운트, privileged 옵션은 위험도가 큽니다.",
            "비밀값은 이미지에 굽지 말고 런타임에 주입합니다.",
        ],
        [
            ("최소 권한", "필요한 capabilities만 남기고 기본 권한을 줄입니다."),
            ("스캔", "이미지 취약점 스캔과 의존성 스캔을 CI에 넣습니다."),
            ("비밀 관리", "Jenkins Credentials, Kubernetes Secret, 외부 secret manager를 사용합니다."),
            ("런타임 정책", "쓰기 가능한 경로, 네트워크, 사용자, 리소스 제한을 명시합니다."),
        ],
        """
        FROM nginx:1.27-alpine
        COPY ./html /usr/share/nginx/html
        RUN addgroup -S app && adduser -S app -G app
        USER app
        """,
        [
            "Docker socket을 아무 컨테이너에나 마운트하는 실수",
            "이미지에 `.env`나 인증서를 복사하는 실수",
            "`--privileged`로 권한 문제를 쉽게 해결하려는 실수",
        ],
        [
            "현재 사용하는 이미지의 베이스 이미지와 사용자 정보를 확인하세요.",
            "Dockerfile에서 `USER`를 지정하고 실행 권한 문제를 해결해보세요.",
            "불필요하게 publish된 포트를 찾아 제거하세요.",
        ],
        [
            "컨테이너 root와 호스트 root의 관계를 설명할 수 있는가?",
            "이미지 안에 비밀값을 넣으면 어떤 경로로 유출될 수 있는가?",
            "Docker socket 마운트가 왜 위험한가?",
        ],
    ),
    base_chapter(
        "advanced", "운영 디버깅과 장애 대응",
        "Docker 장애 대응은 컨테이너 상태, 로그, 네트워크, 파일시스템, 이미지 변경 이력을 순서대로 좁히는 일입니다.",
        ["증상", "컨테이너 상태", "로그", "네트워크", "볼륨", "이미지 변경"],
        [
            "먼저 컨테이너가 실행 중인지 확인합니다.",
            "다음은 로그입니다. 애플리케이션이 왜 종료됐는지 대부분 로그에 있습니다.",
            "연결 문제는 포트 publish, 내부 DNS, 컨테이너 리스닝 주소를 확인합니다.",
            "데이터 문제는 볼륨 마운트 경로와 권한을 확인합니다.",
        ],
        [
            ("명령 순서", "`docker ps`, `docker logs`, `docker inspect`, `docker exec`, `docker network inspect` 순으로 봅니다."),
            ("재현", "운영 컨테이너에 직접 수정하지 말고 같은 이미지와 설정으로 재현 환경을 만듭니다."),
            ("롤백", "이미지 태그가 명확하면 이전 정상 버전으로 빠르게 되돌릴 수 있습니다."),
            ("사후 분석", "장애 후 Dockerfile, Compose, CI 태그 정책까지 원인을 확장해 봅니다."),
        ],
        """
        docker ps -a
        docker logs --tail 200 app
        docker inspect app
        docker exec -it app sh
        docker network inspect app_default
        docker stats
        """,
        [
            "컨테이너가 재시작 중인데 애플리케이션 문제인지 Docker 문제인지 구분하지 못하는 실수",
            "로그를 보지 않고 이미지만 재빌드하는 실수",
            "컨테이너 안에서 임시 수정 후 원인을 기록하지 않는 실수",
        ],
        [
            "일부러 잘못된 환경변수로 앱을 띄우고 로그에서 원인을 찾으세요.",
            "포트 매핑을 빼고 접근 실패를 재현한 뒤 inspect로 확인하세요.",
            "컨테이너 메모리 사용량을 `docker stats`로 관찰하세요.",
        ],
        [
            "컨테이너가 계속 죽을 때 첫 세 명령은 무엇인가?",
            "네트워크 문제와 앱 설정 문제를 어떻게 구분할 것인가?",
            "롤백 가능한 Docker 운영의 전제는 무엇인가?",
        ],
    ),
]


JENKINS = [
    base_chapter(
        "beginner", "CI/CD와 Jenkins의 역할",
        "Jenkins는 코드를 가져와 빌드, 테스트, 패키징, 배포를 자동화하는 서버입니다.",
        ["Git push", "Jenkins trigger", "Build", "Test", "Package", "Deploy"],
        [
            "사람이 로컬에서 하던 반복 작업을 서버가 대신 하게 만드는 것이 CI의 출발점입니다.",
            "CD는 검증된 산출물을 환경에 전달하는 과정을 자동화합니다.",
            "Jenkins는 플러그인과 Pipeline으로 다양한 도구를 연결합니다.",
            "초보자는 Jenkins를 자동 버튼으로 이해하고, 실무자는 변경 흐름을 통제하는 감사 가능한 시스템으로 봅니다.",
        ],
        [
            ("반복성", "누가 실행해도 같은 단계가 같은 순서로 돌아야 합니다."),
            ("가시성", "어느 단계에서 실패했는지 팀 전체가 볼 수 있어야 합니다."),
            ("권한", "배포 권한은 사람 PC가 아니라 Jenkins Credentials와 승인 절차로 관리합니다."),
            ("품질문", "Pipeline은 단순 자동화가 아니라 코드 품질 기준을 통과시키는 문입니다."),
        ],
        """
        pipeline {
          agent any
          stages {
            stage('Build') { steps { sh 'make build' } }
            stage('Test') { steps { sh 'make test' } }
            stage('Deploy') { steps { sh 'make deploy' } }
          }
        }
        """,
        [
            "Jenkins를 배포 버튼 정도로만 쓰고 테스트와 검증을 생략하는 실수",
            "개발자 로컬 환경에만 있는 도구에 의존하는 실수",
            "실패한 빌드를 무시하고 수동 배포로 우회하는 실수",
        ],
        [
            "현재 프로젝트에서 사람이 반복하는 빌드/테스트/배포 절차를 적어보세요.",
            "각 절차가 실패했을 때 확인해야 할 로그 위치를 정리하세요.",
            "수동으로 하던 작업 중 Jenkins에 맡길 수 있는 단계를 표시하세요.",
        ],
        [
            "CI와 CD의 차이를 설명할 수 있는가?",
            "Jenkins가 직접 코드를 작성하는 도구가 아닌 이유는 무엇인가?",
            "Pipeline 실패는 팀에게 어떤 정보를 주어야 하는가?",
        ],
    ),
    base_chapter(
        "beginner", "Controller, Agent, Job",
        "Jenkins 구조는 지시를 관리하는 controller와 실제 작업을 실행하는 agent로 나뉩니다.",
        ["Controller", "Queue", "Agent", "Workspace", "Build result"],
        [
            "Controller는 UI, 설정, 큐, 작업 정의를 관리합니다.",
            "Agent는 실제 빌드 명령을 실행하는 작업자입니다.",
            "Job은 자동화 정의이고, Build는 그 Job의 한 번 실행 결과입니다.",
            "Workspace는 소스가 체크아웃되고 빌드가 수행되는 작업 폴더입니다.",
        ],
        [
            ("격리", "무거운 빌드는 controller가 아니라 agent에서 돌리는 것이 좋습니다."),
            ("스케일", "팀 규모가 커지면 agent를 늘려 병렬 빌드 처리량을 올립니다."),
            ("정리", "workspace가 쌓이면 디스크를 잡아먹으므로 정리 정책이 필요합니다."),
            ("장애 범위", "controller 장애와 agent 장애는 영향 범위가 다릅니다."),
        ],
        """
        # 관리 화면에서 확인할 것
        Manage Jenkins -> Nodes
        Manage Jenkins -> System
        Job -> Workspace
        Job -> Build History
        """,
        [
            "controller에서 모든 빌드를 실행해 Jenkins 자체가 느려지는 실수",
            "workspace에 남은 이전 산출물이 다음 빌드에 영향을 주는 실수",
            "agent label을 설계하지 않아 필요한 도구가 없는 agent에서 빌드가 도는 실수",
        ],
        [
            "Jenkins 화면에서 현재 노드와 executor 수를 확인하세요.",
            "하나의 Job을 두 번 실행하고 Build 번호가 어떻게 늘어나는지 보세요.",
            "workspace에 어떤 파일이 남는지 확인하고 정리 방법을 찾아보세요.",
        ],
        [
            "Job과 Build는 어떻게 다른가?",
            "왜 controller에서 무거운 빌드를 피해야 하는가?",
            "agent label은 어떤 상황에서 필요한가?",
        ],
    ),
    base_chapter(
        "basic", "Pipeline as Code와 Jenkinsfile",
        "Pipeline as Code는 빌드 절차를 Jenkins UI가 아니라 저장소 안의 Jenkinsfile로 관리하는 방식입니다.",
        ["Repository", "Jenkinsfile", "Code review", "Pipeline run", "Audit trail"],
        [
            "UI에서 만든 Job은 변경 이력을 추적하기 어렵습니다.",
            "Jenkinsfile은 애플리케이션 코드와 함께 리뷰되고 버전 관리됩니다.",
            "Declarative Pipeline은 읽기 쉬운 구조를 제공해 팀 표준화에 좋습니다.",
            "Scripted Pipeline은 유연하지만 초보자와 팀 운영에서는 복잡해질 수 있습니다.",
        ],
        [
            ("단일 진실", "빌드 절차의 기준은 저장소의 Jenkinsfile이어야 합니다."),
            ("리뷰", "배포 절차 변경도 코드 리뷰 대상입니다."),
            ("재사용", "반복되는 로직은 Shared Library로 빼되 너무 일찍 추상화하지 않습니다."),
            ("감사", "누가 언제 배포 로직을 바꿨는지 Git 기록으로 남습니다."),
        ],
        """
        pipeline {
          agent any
          options {
            timestamps()
            disableConcurrentBuilds()
          }
          stages {
            stage('Checkout') { steps { checkout scm } }
            stage('Test') { steps { sh './gradlew test' } }
          }
          post {
            always { junit 'build/test-results/test/*.xml' }
          }
        }
        """,
        [
            "중요한 배포 명령을 Jenkins UI의 숨은 설정에만 넣는 실수",
            "Jenkinsfile에서 너무 많은 Groovy 로직을 작성해 유지보수가 어려워지는 실수",
            "Pipeline 변경을 코드 리뷰 없이 바로 적용하는 실수",
        ],
        [
            "간단한 Jenkinsfile을 저장소 루트에 작성해보세요.",
            "Build, Test, Package 세 stage를 나누고 실패 지점을 확인하세요.",
            "Jenkinsfile 변경을 커밋으로 남기는 흐름을 연습하세요.",
        ],
        [
            "Pipeline as Code가 UI 설정보다 좋은 이유는 무엇인가?",
            "Declarative Pipeline과 Scripted Pipeline의 차이는 무엇인가?",
            "배포 로직 변경을 코드 리뷰해야 하는 이유는 무엇인가?",
        ],
    ),
    base_chapter(
        "basic", "Stage, Step, Post 처리",
        "Pipeline은 stage라는 큰 단계와 step이라는 실제 명령으로 구성됩니다. post는 결과에 따른 후처리를 담당합니다.",
        ["Stage: Build", "Stage: Test", "Stage: Scan", "Stage: Deploy", "Post actions"],
        [
            "stage는 사람이 이해하는 업무 단계입니다.",
            "step은 Jenkins가 실제 실행하는 명령입니다.",
            "post 블록은 성공, 실패, 항상 실행 같은 결과별 처리를 정의합니다.",
            "좋은 Pipeline은 실패 지점이 화면만 봐도 보입니다.",
        ],
        [
            ("가독성", "stage 이름은 팀원이 보는 운영 언어로 작성합니다."),
            ("결과 수집", "테스트 실패 시에도 리포트를 수집하려면 post나 catchError를 사용합니다."),
            ("알림", "실패 알림은 원인 링크와 로그 위치를 포함해야 합니다."),
            ("정리", "임시 파일, 컨테이너, credentials 파일은 후처리에서 정리합니다."),
        ],
        """
        pipeline {
          agent any
          stages {
            stage('Unit Test') {
              steps { sh './gradlew test' }
              post { always { junit 'build/test-results/test/*.xml' } }
            }
          }
          post {
            failure { echo 'Notify team' }
            cleanup { cleanWs() }
          }
        }
        """,
        [
            "모든 명령을 하나의 stage에 넣어 실패 위치를 알 수 없게 만드는 실수",
            "테스트가 실패하면 리포트 수집 단계도 건너뛰는 실수",
            "후처리에서 workspace나 임시 인증 파일을 정리하지 않는 실수",
        ],
        [
            "Pipeline stage를 최소 4개로 나누고 의도적으로 Test를 실패시켜보세요.",
            "실패해도 junit 리포트가 수집되는지 확인하세요.",
            "post cleanup에서 workspace 정리를 적용해보세요.",
        ],
        [
            "stage와 step의 차이는 무엇인가?",
            "post always는 어떤 상황에서 유용한가?",
            "실패한 Pipeline이 남겨야 하는 정보는 무엇인가?",
        ],
    ),
    base_chapter(
        "intermediate", "Credentials와 비밀 관리",
        "Jenkins에서 토큰, 비밀번호, SSH 키는 코드가 아니라 Credentials 저장소에서 관리해야 합니다.",
        ["Credentials Store", "Binding", "Pipeline env", "External system"],
        [
            "비밀값은 저장소에 커밋되면 회수하기 어렵습니다.",
            "Jenkins Credentials는 Pipeline 실행 중 필요한 범위에만 값을 주입합니다.",
            "withCredentials 블록 밖으로 비밀값이 새지 않게 해야 합니다.",
            "로그에 비밀값이 출력되지 않도록 명령어와 스크립트를 조심해야 합니다.",
        ],
        [
            ("범위", "folder, job, global 범위를 나누어 최소 노출을 지향합니다."),
            ("회전", "토큰은 만료와 교체 절차가 있어야 합니다."),
            ("권한", "Jenkins 관리 권한과 배포 권한을 분리합니다."),
            ("감사", "누가 어떤 credential을 사용할 수 있는지 주기적으로 검토합니다."),
        ],
        """
        withCredentials([string(credentialsId: 'registry-token', variable: 'REG_TOKEN')]) {
          sh '''
            echo "$REG_TOKEN" | docker login registry.example.com \\
              --username robot --password-stdin
          '''
        }
        """,
        [
            "토큰을 Jenkinsfile에 직접 쓰는 실수",
            "`set -x`로 쉘 명령과 비밀값이 로그에 노출되는 실수",
            "모든 Job이 모든 Credential을 쓸 수 있게 두는 실수",
        ],
        [
            "테스트용 string credential을 만들고 Pipeline에서 사용해보세요.",
            "로그에 값이 마스킹되는지 확인하세요.",
            "folder 단위 credential 범위를 실험해보세요.",
        ],
        [
            "Credentials와 환경변수의 관계를 설명할 수 있는가?",
            "비밀값이 로그에 새는 대표 원인은 무엇인가?",
            "토큰 회전 절차가 필요한 이유는 무엇인가?",
        ],
    ),
    base_chapter(
        "intermediate", "Docker와 Jenkins Pipeline",
        "Jenkins는 Docker 이미지를 빌드하고, 컨테이너 안에서 테스트를 실행하고, 레지스트리에 push할 수 있습니다.",
        ["Checkout", "docker build", "container test", "docker push", "deploy"],
        [
            "Docker를 쓰면 Jenkins agent에 모든 런타임을 설치하지 않아도 됩니다.",
            "빌드 산출물을 이미지로 만들면 배포 단위가 명확해집니다.",
            "테스트를 컨테이너로 실행하면 로컬과 CI의 차이를 줄일 수 있습니다.",
            "Docker daemon 접근 권한은 강력하므로 agent 격리가 중요합니다.",
        ],
        [
            ("빌드 환경", "도구 버전을 이미지로 고정하면 agent 차이가 줄어듭니다."),
            ("캐시", "Docker build cache와 의존성 캐시를 설계하면 CI 시간이 줄어듭니다."),
            ("보안", "Docker socket 접근은 사실상 호스트 제어권에 가깝습니다."),
            ("추적", "Jenkins 빌드 번호와 Git SHA를 이미지 태그에 넣습니다."),
        ],
        """
        pipeline {
          agent any
          environment {
            IMAGE = "registry.example.com/team/app:${env.BUILD_NUMBER}"
          }
          stages {
            stage('Build image') { steps { sh 'docker build -t $IMAGE .' } }
            stage('Test image') { steps { sh 'docker run --rm $IMAGE npm test' } }
            stage('Push') { steps { sh 'docker push $IMAGE' } }
          }
        }
        """,
        [
            "Jenkins agent에 직접 설치된 오래된 도구에 빌드가 의존하는 실수",
            "Docker socket을 공유하면서 신뢰할 수 없는 Job도 같은 agent에서 실행하는 실수",
            "이미지 태그와 Jenkins 빌드 번호를 연결하지 않는 실수",
        ],
        [
            "Jenkins에서 Docker 이미지를 빌드하는 stage를 작성하세요.",
            "빌드한 이미지를 `docker run --rm`으로 테스트하세요.",
            "이미지 태그에 빌드 번호와 Git SHA를 넣어보세요.",
        ],
        [
            "Jenkins에서 Docker를 쓰는 장점과 위험은 각각 무엇인가?",
            "이미지를 테스트한 뒤 push해야 하는 이유는 무엇인가?",
            "Docker build cache가 CI 시간에 주는 영향은 무엇인가?",
        ],
    ),
    base_chapter(
        "practical", "멀티브랜치, PR 검증, 품질 게이트",
        "실무 CI는 main 브랜치만 빌드하지 않습니다. 브랜치와 Pull Request를 자동 검증해야 합니다.",
        ["Feature branch", "Pull Request", "CI validation", "Code review", "Merge"],
        [
            "변경은 main에 합쳐지기 전에 검증되어야 합니다.",
            "멀티브랜치 Pipeline은 브랜치별 Jenkinsfile을 읽어 자동으로 Job을 구성합니다.",
            "품질 게이트는 테스트, 린트, 보안 스캔, 커버리지 같은 기준입니다.",
            "게이트는 개발 속도를 막는 벽이 아니라 장애를 줄이는 안전장치입니다.",
        ],
        [
            ("PR 피드백", "실패 원인을 PR 화면에서 바로 알 수 있게 연동합니다."),
            ("빠른 실패", "lint와 단위 테스트를 앞에 두어 빠르게 피드백합니다."),
            ("필수 검사", "main merge 전에 통과해야 하는 check를 저장소 정책으로 설정합니다."),
            ("예외 관리", "품질 게이트 예외는 기록과 만료일을 둡니다."),
        ],
        """
        stages {
          stage('Fast checks') {
            parallel {
              stage('Lint') { steps { sh 'npm run lint' } }
              stage('Unit') { steps { sh 'npm test' } }
              stage('Security') { steps { sh 'npm audit --audit-level=high' } }
            }
          }
        }
        """,
        [
            "main에 merge된 뒤에야 테스트를 돌리는 실수",
            "느린 통합 테스트를 앞에 두어 피드백이 늦어지는 실수",
            "품질 게이트 실패를 무시하고 수동 배포하는 실수",
        ],
        [
            "PR용 Pipeline과 main용 Pipeline의 차이를 설계해보세요.",
            "lint, unit test, build를 parallel로 돌려보세요.",
            "품질 게이트 실패 시 merge를 막는 저장소 설정을 확인하세요.",
        ],
        [
            "멀티브랜치 Pipeline이 필요한 이유는 무엇인가?",
            "빠른 실패 전략은 왜 중요한가?",
            "품질 게이트 예외는 어떻게 관리해야 하는가?",
        ],
    ),
    base_chapter(
        "practical", "Jenkins 운영과 보안",
        "Jenkins 자체도 운영 시스템입니다. 백업, 업그레이드, 권한, 플러그인 관리가 필요합니다.",
        ["JENKINS_HOME", "Plugins", "Users/RBAC", "Backups", "Upgrade"],
        [
            "Jenkins 설정과 Job 이력은 JENKINS_HOME에 저장됩니다.",
            "플러그인은 Jenkins의 힘이지만 동시에 업그레이드 리스크입니다.",
            "관리자 권한은 최소 인원에게만 주어야 합니다.",
            "업그레이드는 LTS 기준으로 테스트 환경에서 먼저 검증합니다.",
        ],
        [
            ("백업", "JENKINS_HOME, credentials, plugin 목록, Job 설정을 백업합니다."),
            ("권한", "관리자, 개발자, 조회자, 배포 승인자 권한을 분리합니다."),
            ("플러그인", "불필요한 플러그인을 줄이고 업데이트 전 변경 로그를 확인합니다."),
            ("감사", "누가 Job 설정과 Credential을 바꿨는지 추적합니다."),
        ],
        """
        # 백업 대상 예시
        $JENKINS_HOME/jobs
        $JENKINS_HOME/credentials.xml
        $JENKINS_HOME/secrets
        $JENKINS_HOME/plugins.txt
        """,
        [
            "JENKINS_HOME 백업 없이 서버를 운영하는 실수",
            "모든 팀원에게 관리자 권한을 주는 실수",
            "플러그인을 한꺼번에 업데이트하고 장애 원인을 모르게 되는 실수",
        ],
        [
            "현재 Jenkins 플러그인 목록을 내보내는 방법을 확인하세요.",
            "Job 설정 변경 권한과 빌드 실행 권한을 분리해보세요.",
            "백업 복구 리허설 절차를 문서화하세요.",
        ],
        [
            "JENKINS_HOME이 중요한 이유는 무엇인가?",
            "플러그인 업데이트 전 확인해야 할 것은 무엇인가?",
            "Jenkins 관리자 권한을 최소화해야 하는 이유는 무엇인가?",
        ],
    ),
    base_chapter(
        "advanced", "실패 분석과 Pipeline 개선",
        "좋은 Jenkins 운영자는 실패를 없애기보다 실패가 빠르고 명확하게 드러나도록 Pipeline을 설계합니다.",
        ["Failure", "Logs", "Artifacts", "Root cause", "Pipeline improvement"],
        [
            "실패는 환경 문제, 코드 문제, 테스트 불안정성, 외부 시스템 문제로 나눠 봅니다.",
            "로그와 산출물이 남아야 원인을 추적할 수 있습니다.",
            "재시도는 임시 네트워크 문제에는 유용하지만 코드 결함을 숨기면 안 됩니다.",
            "반복 실패는 Pipeline 설계 개선의 신호입니다.",
        ],
        [
            ("Flaky test", "불안정 테스트는 별도로 추적하고 격리해야 합니다."),
            ("타임아웃", "무한 대기를 막기 위해 stage별 timeout을 둡니다."),
            ("재시도", "외부 API나 registry push 같은 일시 실패에만 제한적으로 적용합니다."),
            ("지표", "빌드 시간, 실패율, 대기시간을 관찰합니다."),
        ],
        """
        options {
          timeout(time: 30, unit: 'MINUTES')
          timestamps()
          buildDiscarder(logRotator(numToKeepStr: '30'))
        }

        retry(2) {
          sh 'docker push $IMAGE'
        }
        """,
        [
            "모든 실패에 무조건 retry를 걸어 진짜 결함을 숨기는 실수",
            "테스트 리포트와 로그를 남기지 않아 실패를 재현할 수 없는 실수",
            "빌드 시간이 계속 늘어나도 측정하지 않는 실수",
        ],
        [
            "stage별 timeout을 추가하고 의도적으로 긴 명령을 실행해보세요.",
            "반복 실패하는 테스트를 flaky로 분류하는 기준을 정하세요.",
            "최근 30개 빌드의 평균 소요 시간을 확인하세요.",
        ],
        [
            "재시도가 적절한 실패와 부적절한 실패는 어떻게 다른가?",
            "Pipeline에 timeout이 필요한 이유는 무엇인가?",
            "빌드 시간 지표는 어떤 개선으로 이어질 수 있는가?",
        ],
    ),
]


KUBERNETES = [
    base_chapter(
        "beginner", "Kubernetes가 해결하는 문제",
        "Kubernetes는 여러 서버 위에서 컨테이너를 배치, 복구, 확장, 연결하는 오케스트레이터입니다.",
        ["컨테이너 이미지", "Pod", "Node", "Cluster", "Service"],
        [
            "Docker는 컨테이너를 만들고 실행하는 데 강합니다.",
            "운영에서는 컨테이너가 어느 서버에서 돌지, 죽으면 누가 살릴지, 어떻게 찾을지가 필요합니다.",
            "Kubernetes는 원하는 상태를 선언하면 컨트롤러가 실제 상태를 맞추는 방식으로 동작합니다.",
            "핵심 사고방식은 명령 실행이 아니라 원하는 상태 선언입니다.",
        ],
        [
            ("자기복구", "Pod가 죽으면 컨트롤러가 새 Pod를 만들 수 있습니다."),
            ("확장", "replica 수를 늘려 여러 Pod로 트래픽을 나눕니다."),
            ("서비스 발견", "Pod IP가 바뀌어도 Service 이름으로 접근합니다."),
            ("표준화", "배포, 설정, 네트워크, 저장소를 API 객체로 관리합니다."),
        ],
        """
        kubectl create deployment web --image=nginx:1.27
        kubectl expose deployment web --port=80 --type=ClusterIP
        kubectl get pods,svc
        """,
        [
            "Kubernetes를 Docker보다 복잡한 실행 명령 모음으로만 이해하는 실수",
            "Pod IP에 직접 의존하는 실수",
            "선언한 desired state와 실제 current state를 구분하지 못하는 실수",
        ],
        [
            "Deployment를 만들고 Pod가 생성되는 것을 확인하세요.",
            "Pod를 삭제한 뒤 새 Pod가 자동 생성되는지 확인하세요.",
            "Service가 Pod 변경과 무관하게 유지되는지 확인하세요.",
        ],
        [
            "Kubernetes에서 원하는 상태란 무엇인가?",
            "Pod가 죽어도 서비스가 유지될 수 있는 이유는 무엇인가?",
            "Docker Compose와 Kubernetes의 차이를 말할 수 있는가?",
        ],
    ),
    base_chapter(
        "beginner", "클러스터, Control Plane, Node",
        "Kubernetes 클러스터는 결정을 내리는 control plane과 실제 Pod를 실행하는 node들로 구성됩니다.",
        ["kubectl", "API Server", "Scheduler", "Controller Manager", "Kubelet", "Container Runtime"],
        [
            "kubectl은 API Server에 요청을 보냅니다.",
            "API Server는 Kubernetes의 정문입니다.",
            "Scheduler는 새 Pod를 어느 Node에 둘지 결정합니다.",
            "Kubelet은 각 Node에서 Pod가 실제로 실행되도록 관리합니다.",
        ],
        [
            ("장애 분리", "control plane 문제와 node 문제는 증상이 다릅니다."),
            ("용량", "Node CPU와 메모리가 부족하면 Pod가 Pending 상태에 머뭅니다."),
            ("업그레이드", "클러스터 버전과 API 버전 호환성을 관리해야 합니다."),
            ("관찰", "Node 상태, 이벤트, kubelet 로그를 볼 수 있어야 합니다."),
        ],
        """
        kubectl cluster-info
        kubectl get nodes -o wide
        kubectl describe node <node-name>
        kubectl get events --sort-by=.lastTimestamp
        """,
        [
            "Pod Pending을 애플리케이션 버그로만 보는 실수",
            "kubectl이 직접 Node에 명령한다고 생각하는 실수",
            "Node 자원 부족과 이미지 pull 실패를 구분하지 못하는 실수",
        ],
        [
            "로컬 클러스터에서 `kubectl get nodes` 결과를 해석하세요.",
            "Pod를 일부러 너무 큰 CPU request로 만들어 Pending을 재현하세요.",
            "이벤트를 시간순으로 확인해 원인을 찾아보세요.",
        ],
        [
            "API Server의 역할은 무엇인가?",
            "Scheduler와 kubelet의 역할은 어떻게 다른가?",
            "Pod가 Pending일 때 가장 먼저 볼 정보는 무엇인가?",
        ],
    ),
    base_chapter(
        "basic", "Pod와 컨테이너 생명주기",
        "Pod는 Kubernetes에서 배포되는 가장 작은 실행 단위이며, 하나 이상의 컨테이너를 함께 담습니다.",
        ["Pod spec", "Container", "Image pull", "Running", "Terminating"],
        [
            "Kubernetes는 컨테이너를 직접 배포하기보다 Pod라는 껍데기에 담습니다.",
            "같은 Pod의 컨테이너들은 네트워크와 일부 볼륨을 공유합니다.",
            "Pod는 대체 가능한 존재입니다. 이름과 IP에 집착하면 안 됩니다.",
            "Pod 상태와 컨테이너 상태는 구분해서 봐야 합니다.",
        ],
        [
            ("단일 책임", "대부분의 앱은 Pod 하나에 주요 앱 컨테이너 하나를 둡니다."),
            ("Sidecar", "로그 수집, 프록시, 보조 기능은 sidecar로 붙을 수 있습니다."),
            ("종료 처리", "SIGTERM과 graceful shutdown을 구현해야 롤링 업데이트가 안전합니다."),
            ("디버깅", "`logs`, `describe`, `exec`가 기본 3종입니다."),
        ],
        """
        apiVersion: v1
        kind: Pod
        metadata:
          name: nginx-pod
        spec:
          containers:
            - name: nginx
              image: nginx:1.27
              ports:
                - containerPort: 80
        """,
        [
            "Pod를 영구 서버처럼 생각하고 직접 수정하는 실수",
            "Pod 안의 localhost 공유 특성을 모르고 sidecar 통신을 오해하는 실수",
            "종료 신호를 처리하지 않아 배포 때 요청이 끊기는 실수",
        ],
        [
            "Pod YAML을 직접 적용하고 로그를 확인하세요.",
            "Pod 안에서 `hostname`과 네트워크 인터페이스를 확인하세요.",
            "Pod 삭제 후 같은 이름으로 다시 만들 때 IP가 바뀌는지 보세요.",
        ],
        [
            "Pod와 컨테이너는 어떤 관계인가?",
            "Pod IP에 의존하면 왜 위험한가?",
            "graceful shutdown이 필요한 이유는 무엇인가?",
        ],
    ),
    base_chapter(
        "basic", "Deployment와 롤링 업데이트",
        "Deployment는 ReplicaSet을 통해 원하는 수의 Pod를 유지하고, 이미지 변경 시 롤링 업데이트를 수행합니다.",
        ["Deployment", "ReplicaSet", "Pod replicas", "Rolling update", "Rollback"],
        [
            "Pod를 직접 만들면 죽었을 때 자동 복구가 약합니다.",
            "Deployment는 원하는 replica 수를 선언하고 유지합니다.",
            "이미지를 바꾸면 새 ReplicaSet을 만들고 새 Pod로 점진 교체합니다.",
            "문제가 생기면 이전 ReplicaSet으로 롤백할 수 있습니다.",
        ],
        [
            ("무중단", "readinessProbe와 적절한 rollingUpdate 설정이 있어야 안전합니다."),
            ("버전 추적", "이미지 태그와 annotation에 Git SHA를 남깁니다."),
            ("배포 전략", "소규모는 RollingUpdate, 복잡한 환경은 blue-green/canary 도구를 검토합니다."),
            ("되돌리기", "`kubectl rollout undo`는 빠른 응급 복구 수단입니다."),
        ],
        """
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: web
        spec:
          replicas: 3
          selector:
            matchLabels:
              app: web
          template:
            metadata:
              labels:
                app: web
            spec:
              containers:
                - name: web
                  image: nginx:1.27
                  ports:
                    - containerPort: 80
        """,
        [
            "readinessProbe 없이 트래픽을 새 Pod로 바로 보내는 실수",
            "이미지 태그를 `latest`로 두어 업데이트 감지가 애매해지는 실수",
            "ReplicaSet과 Pod를 직접 수정해 Deployment가 다시 덮어쓰는 실수",
        ],
        [
            "Deployment replicas를 1에서 3으로 늘려보세요.",
            "이미지 버전을 바꾸고 rollout status를 확인하세요.",
            "잘못된 이미지로 배포한 뒤 rollout undo를 수행하세요.",
        ],
        [
            "Deployment와 ReplicaSet의 관계는 무엇인가?",
            "롤링 업데이트가 안전하려면 어떤 probe가 중요한가?",
            "왜 `latest` 태그가 Kubernetes 배포에서 문제를 만들 수 있는가?",
        ],
    ),
    base_chapter(
        "intermediate", "Service와 네트워크",
        "Service는 바뀌는 Pod 집합 앞에 안정적인 이름과 가상 IP를 제공합니다.",
        ["Client", "Service DNS", "Service", "EndpointSlice", "Pods"],
        [
            "Pod는 생성되고 삭제되며 IP가 바뀝니다.",
            "Service는 label selector로 대상 Pod를 찾습니다.",
            "클러스터 안에서는 Service 이름으로 접근합니다.",
            "외부 노출은 ClusterIP, NodePort, LoadBalancer, Ingress 같은 선택지가 있습니다.",
        ],
        [
            ("내부 안정성", "애플리케이션은 Pod IP 대신 Service DNS를 사용합니다."),
            ("라벨", "selector가 잘못되면 Service에 endpoint가 없어집니다."),
            ("외부 노출", "운영에서는 보통 Ingress나 LoadBalancer를 통해 진입점을 관리합니다."),
            ("진단", "`kubectl get endpointslice`, `describe svc`, `nslookup`으로 추적합니다."),
        ],
        """
        apiVersion: v1
        kind: Service
        metadata:
          name: web
        spec:
          selector:
            app: web
          ports:
            - port: 80
              targetPort: 80
          type: ClusterIP
        """,
        [
            "Service selector와 Pod label이 달라 endpoint가 비어 있는 실수",
            "targetPort와 port를 혼동하는 실수",
            "모든 서비스를 LoadBalancer로 외부 노출하는 실수",
        ],
        [
            "Deployment와 Service를 만들고 Service DNS로 접근해보세요.",
            "label을 일부러 바꿔 endpoint가 사라지는 것을 확인하세요.",
            "ClusterIP와 NodePort의 차이를 실험하세요.",
        ],
        [
            "Service가 필요한 이유는 무엇인가?",
            "selector와 label의 관계를 설명할 수 있는가?",
            "port와 targetPort의 차이는 무엇인가?",
        ],
    ),
    base_chapter(
        "intermediate", "ConfigMap과 Secret",
        "설정과 비밀값은 이미지에 넣지 않고 Kubernetes 객체로 분리해 Pod에 주입합니다.",
        ["ConfigMap", "Secret", "Env vars", "Mounted files", "Pod"],
        [
            "ConfigMap은 비밀이 아닌 설정값을 담습니다.",
            "Secret은 비밀번호, 토큰, 인증서처럼 민감한 값을 담습니다.",
            "둘 다 환경변수나 파일 마운트로 Pod에 전달할 수 있습니다.",
            "Secret은 이름이 Secret이라고 해서 자동으로 완벽히 안전한 것은 아니며 접근 권한과 암호화 설정이 중요합니다.",
        ],
        [
            ("이미지 재사용", "환경별 설정을 분리하면 같은 이미지를 dev, stage, prod에 배포할 수 있습니다."),
            ("권한", "Secret 조회 권한을 RBAC로 제한합니다."),
            ("교체", "설정 변경이 Pod 재시작을 필요로 하는지 애플리케이션 특성에 따라 다릅니다."),
            ("외부 연동", "운영에서는 Vault, cloud secret manager, external-secrets 같은 도구를 고려합니다."),
        ],
        """
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: app-config
        data:
          LOG_LEVEL: info
        ---
        apiVersion: v1
        kind: Secret
        metadata:
          name: app-secret
        type: Opaque
        stringData:
          DB_PASSWORD: change-me
        """,
        [
            "비밀번호를 ConfigMap에 넣는 실수",
            "Secret을 Git 저장소에 평문 YAML로 커밋하는 실수",
            "설정 변경 후 Pod가 자동으로 모든 값을 다시 읽는다고 착각하는 실수",
        ],
        [
            "ConfigMap을 만들고 Pod 환경변수로 주입하세요.",
            "Secret을 만들고 권한 있는 사용자만 조회할 수 있게 RBAC를 생각해보세요.",
            "ConfigMap 값을 바꾼 뒤 Pod에 반영되는 방식을 확인하세요.",
        ],
        [
            "ConfigMap과 Secret의 차이는 무엇인가?",
            "Secret이 안전하려면 어떤 조건이 필요한가?",
            "같은 이미지를 여러 환경에 쓰려면 무엇을 분리해야 하는가?",
        ],
    ),
    base_chapter(
        "intermediate", "Probe와 리소스 관리",
        "Kubernetes는 컨테이너가 살아 있는지, 트래픽을 받을 준비가 됐는지, 시작 중인지 probe로 판단합니다.",
        ["Startup probe", "Liveness probe", "Readiness probe", "Service traffic", "Restart"],
        [
            "livenessProbe는 죽은 프로세스를 재시작하기 위한 신호입니다.",
            "readinessProbe는 트래픽을 받을 준비가 됐는지 판단합니다.",
            "startupProbe는 느리게 시작하는 앱이 liveness에 의해 너무 빨리 죽는 것을 막습니다.",
            "requests와 limits는 스케줄링과 자원 격리를 위해 필요합니다.",
        ],
        [
            ("무중단 배포", "readiness가 false인 Pod에는 Service 트래픽이 가지 않아야 합니다."),
            ("재시작 루프", "liveness가 너무 엄격하면 정상 앱도 반복 재시작될 수 있습니다."),
            ("용량 계획", "requests 합계가 Node 배치 가능성을 결정합니다."),
            ("성능", "limit가 낮으면 throttling이나 OOMKill이 발생할 수 있습니다."),
        ],
        """
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
          limits:
            cpu: "1"
            memory: "512Mi"
        """,
        [
            "readiness와 liveness를 같은 endpoint로 대충 처리하는 실수",
            "resources를 비워두어 스케줄링과 용량 계획이 어려워지는 실수",
            "메모리 limit를 너무 낮게 잡아 OOMKill을 반복하는 실수",
        ],
        [
            "readinessProbe를 실패시키고 Service endpoint에서 빠지는지 확인하세요.",
            "메모리 limit를 낮춰 OOMKilled 상태를 재현해보세요.",
            "requests 값을 바꿔 Pod 스케줄링 변화를 관찰하세요.",
        ],
        [
            "readiness와 liveness의 차이는 무엇인가?",
            "requests는 어떤 결정에 쓰이는가?",
            "OOMKilled와 CrashLoopBackOff를 어떻게 구분할 것인가?",
        ],
    ),
    base_chapter(
        "practical", "Ingress, TLS, 외부 트래픽",
        "Ingress는 외부 HTTP 트래픽을 클러스터 내부 Service로 라우팅하는 대표 방식입니다.",
        ["User", "DNS", "Load Balancer", "Ingress Controller", "Service", "Pods"],
        [
            "Ingress 리소스만으로는 동작하지 않고 Ingress Controller가 필요합니다.",
            "Host와 path 규칙으로 여러 서비스를 하나의 진입점 뒤에 둘 수 있습니다.",
            "TLS 인증서는 Secret으로 연결하는 방식이 흔합니다.",
            "최근 환경에서는 Gateway API도 점점 많이 검토됩니다.",
        ],
        [
            ("진입점 표준화", "도메인, TLS, 라우팅, 인증 정책을 한 곳에서 관리합니다."),
            ("컨트롤러 차이", "nginx, traefik, cloud LB controller마다 annotation과 기능이 다릅니다."),
            ("보안", "HTTP를 HTTPS로 리다이렉트하고 TLS 정책을 관리합니다."),
            ("관찰", "Ingress access log와 애플리케이션 log를 함께 봅니다."),
        ],
        """
        apiVersion: networking.k8s.io/v1
        kind: Ingress
        metadata:
          name: web
        spec:
          rules:
            - host: app.example.com
              http:
                paths:
                  - path: /
                    pathType: Prefix
                    backend:
                      service:
                        name: web
                        port:
                          number: 80
        """,
        [
            "Ingress 리소스만 만들고 Controller가 없어서 동작하지 않는 실수",
            "Service port와 backend port를 혼동하는 실수",
            "TLS Secret 갱신 절차를 준비하지 않는 실수",
        ],
        [
            "로컬 클러스터에 Ingress Controller를 설치하고 테스트 도메인으로 접근하세요.",
            "path 기반 라우팅을 두 서비스로 나눠보세요.",
            "TLS Secret 구조를 확인하세요.",
        ],
        [
            "Ingress와 Service는 역할이 어떻게 다른가?",
            "Ingress Controller가 필요한 이유는 무엇인가?",
            "외부 트래픽 장애 시 어느 계층부터 확인할 것인가?",
        ],
    ),
    base_chapter(
        "practical", "Storage, PV, PVC",
        "상태가 있는 애플리케이션은 스토리지를 분리해서 다뤄야 합니다. Kubernetes는 PV와 PVC로 저장소 요청과 공급을 분리합니다.",
        ["Pod", "PVC", "PV", "StorageClass", "Disk"],
        [
            "Pod는 사라질 수 있으므로 중요한 데이터는 Pod 생명주기와 분리해야 합니다.",
            "PVC는 사용자가 요청하는 저장소 청구서입니다.",
            "PV는 실제 제공되는 저장소 자원입니다.",
            "StorageClass는 동적 프로비저닝 정책을 정의합니다.",
        ],
        [
            ("상태 서비스", "DB 운영은 백업, 복구, 스냅샷, 업그레이드까지 포함합니다."),
            ("접근 모드", "ReadWriteOnce, ReadOnlyMany, ReadWriteMany 차이를 이해해야 합니다."),
            ("회수 정책", "PV reclaim policy가 데이터 보존에 영향을 줍니다."),
            ("운영 선택", "중요 DB는 managed DB를 쓰는 것이 더 나은 경우가 많습니다."),
        ],
        """
        apiVersion: v1
        kind: PersistentVolumeClaim
        metadata:
          name: data
        spec:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 10Gi
        """,
        [
            "PVC 삭제가 실제 데이터 삭제로 이어질 수 있음을 모르고 작업하는 실수",
            "여러 Pod가 동시에 써야 하는데 ReadWriteOnce 볼륨을 고르는 실수",
            "백업 없는 StatefulSet을 운영하는 실수",
        ],
        [
            "PVC를 만들고 Pod에 마운트해 파일을 남겨보세요.",
            "Pod 삭제 후 데이터가 유지되는지 확인하세요.",
            "StorageClass와 reclaim policy를 조회하세요.",
        ],
        [
            "PV와 PVC의 차이는 무엇인가?",
            "접근 모드는 왜 중요한가?",
            "Kubernetes 안에서 DB를 운영할 때 가장 중요한 운영 절차는 무엇인가?",
        ],
    ),
    base_chapter(
        "advanced", "운영 디버깅 루틴",
        "Kubernetes 장애 대응은 객체 상태, 이벤트, 로그, 네트워크, 자원, 최근 변경을 계층적으로 좁히는 과정입니다.",
        ["Symptom", "kubectl get", "describe/events", "logs", "exec", "rollout/history"],
        [
            "먼저 어떤 객체가 비정상인지 좁힙니다.",
            "`describe`와 events는 Kubernetes가 왜 그렇게 판단했는지 알려줍니다.",
            "애플리케이션 오류는 logs와 readiness 상태를 봅니다.",
            "최근 배포 변경은 rollout history와 이미지 태그로 추적합니다.",
        ],
        [
            ("Pod Pending", "자원 부족, node selector, taint/toleration, PVC binding을 봅니다."),
            ("CrashLoopBackOff", "컨테이너 로그, 종료 코드, 환경변수, secret mount를 봅니다."),
            ("ImagePullBackOff", "이미지 이름, 태그, registry 인증, 네트워크를 봅니다."),
            ("서비스 불가", "Service endpoint, readiness, Ingress, DNS 순서로 봅니다."),
        ],
        """
        kubectl get deploy,rs,pod,svc,ingress -n app
        kubectl describe pod <pod> -n app
        kubectl logs <pod> -c <container> --previous -n app
        kubectl get events -n app --sort-by=.lastTimestamp
        kubectl rollout history deploy/web -n app
        kubectl rollout undo deploy/web -n app
        """,
        [
            "이벤트를 보지 않고 애플리케이션 로그만 보는 실수",
            "현재 Pod만 보고 Deployment 설정 문제를 놓치는 실수",
            "롤백 가능한 이미지 태그를 남기지 않는 실수",
        ],
        [
            "ImagePullBackOff를 의도적으로 만들고 원인을 찾아보세요.",
            "readiness 실패로 Service endpoint가 비는 상황을 재현하세요.",
            "rollout undo로 정상 버전 복구를 연습하세요.",
        ],
        [
            "Pending, CrashLoopBackOff, ImagePullBackOff의 1차 확인 지점은 무엇인가?",
            "Service 장애에서 endpoint를 확인하는 이유는 무엇인가?",
            "최근 변경 이력은 어디서 확인할 수 있는가?",
        ],
    ),
]


INTEGRATION = [
    base_chapter(
        "beginner", "세 도구의 역할 분담",
        "Docker, Jenkins, Kubernetes는 경쟁 관계가 아니라 하나의 배포 흐름에서 서로 다른 층을 담당합니다.",
        ["Docker: 포장", "Jenkins: 자동화", "Registry: 보관", "Kubernetes: 실행", "Observability: 확인"],
        [
            "Docker는 애플리케이션을 이미지로 포장합니다.",
            "Jenkins는 코드를 가져와 테스트하고 이미지를 만들고 배포 명령을 실행합니다.",
            "Registry는 만들어진 이미지를 저장합니다.",
            "Kubernetes는 이미지를 받아 원하는 수의 Pod로 실행하고 서비스합니다.",
        ],
        [
            ("계약", "Docker 이미지는 CI와 운영 사이의 계약입니다."),
            ("추적", "Git commit, Jenkins build, image tag, Kubernetes rollout을 연결합니다."),
            ("책임 분리", "빌드 문제, 배포 문제, 런타임 문제를 분리해서 진단할 수 있습니다."),
            ("보안", "각 경계마다 인증 정보와 권한을 최소화합니다."),
        ],
        """
        Developer -> Git -> Jenkins -> Docker build -> Registry -> Kubernetes rollout -> Users
        """,
        [
            "Jenkins가 직접 서버에 파일을 복사하는 방식과 이미지 배포 방식을 섞어 추적이 안 되는 실수",
            "빌드한 이미지와 배포한 이미지가 다르게 되는 실수",
            "Kubernetes 장애를 Jenkins 재빌드로 해결하려는 실수",
        ],
        [
            "현재 조직 또는 개인 프로젝트의 배포 흐름을 이 다섯 칸에 맞춰 그려보세요.",
            "각 단계에서 실패하면 어디 로그를 볼지 적으세요.",
            "이미지 태그 규칙을 하나 정하세요.",
        ],
        [
            "Docker, Jenkins, Kubernetes의 책임을 각각 한 문장으로 말할 수 있는가?",
            "이미지가 CI와 운영 사이의 계약이라는 말의 의미는 무엇인가?",
            "장애가 났을 때 어느 계층 문제인지 어떻게 나눌 것인가?",
        ],
    ),
    base_chapter(
        "basic", "샘플 애플리케이션 저장소 구조",
        "실무형 저장소는 앱 코드뿐 아니라 Dockerfile, Jenkinsfile, Kubernetes manifest를 함께 관리합니다.",
        ["src/", "Dockerfile", "Jenkinsfile", "k8s/", "README"],
        [
            "코드만 있으면 배포 절차가 사람 머릿속에 남습니다.",
            "Dockerfile은 실행 환경을 문서화합니다.",
            "Jenkinsfile은 검증과 배포 절차를 문서화합니다.",
            "k8s manifest는 운영에서 원하는 상태를 문서화합니다.",
        ],
        [
            ("온보딩", "새 팀원은 저장소만 보고 빌드와 배포 흐름을 이해할 수 있어야 합니다."),
            ("리뷰", "인프라 변경도 PR에서 리뷰합니다."),
            ("환경 분리", "dev, stage, prod 차이는 overlay나 values로 분리합니다."),
            ("문서", "README에는 로컬 실행, CI, 배포, 롤백 명령이 있어야 합니다."),
        ],
        """
        app/
          src/
          tests/
          Dockerfile
          .dockerignore
          Jenkinsfile
          k8s/
            base/
              deployment.yaml
              service.yaml
            overlays/
              dev/
              prod/
          README.md
        """,
        [
            "배포 YAML을 Jenkins 서버 로컬에만 두는 실수",
            "환경별 manifest를 복사 붙여넣기로 관리해 차이가 누적되는 실수",
            "README가 실행 가능한 절차가 아니라 오래된 설명만 담는 실수",
        ],
        [
            "샘플 저장소 구조를 만들고 각 파일의 책임을 주석으로 적으세요.",
            "dev와 prod에서 달라야 하는 값 목록을 작성하세요.",
            "롤백 절차를 README에 한 문단으로 써보세요.",
        ],
        [
            "Dockerfile, Jenkinsfile, k8s manifest는 각각 무엇을 문서화하는가?",
            "환경별 차이를 안전하게 관리하려면 어떤 원칙이 필요한가?",
            "배포 절차를 저장소에 두는 이유는 무엇인가?",
        ],
    ),
    base_chapter(
        "intermediate", "Jenkins에서 이미지 빌드와 Push",
        "CI의 핵심 산출물은 테스트를 통과한 컨테이너 이미지입니다. 태그와 인증, 스캔이 함께 설계되어야 합니다.",
        ["Checkout", "Test", "Build image", "Scan", "Push registry"],
        [
            "이미지는 테스트가 통과한 코드에서 만들어져야 합니다.",
            "태그는 Git SHA와 빌드 번호를 포함해 추적 가능해야 합니다.",
            "Registry 인증 정보는 Jenkins Credentials에 넣습니다.",
            "Push 전후로 취약점 스캔과 SBOM 생성을 고려합니다.",
        ],
        [
            ("불변 산출물", "stage와 prod에서 이미지를 다시 빌드하지 말고 같은 이미지를 승격합니다."),
            ("보안", "registry push 권한은 CI 전용 계정으로 제한합니다."),
            ("감사", "이미지 label에 source, revision, build URL을 남깁니다."),
            ("속도", "캐시 전략을 통해 CI 시간을 줄입니다."),
        ],
        """
        pipeline {
          agent any
          environment {
            REGISTRY = 'registry.example.com'
            IMAGE = "${REGISTRY}/team/app:${env.GIT_COMMIT.take(7)}-${env.BUILD_NUMBER}"
          }
          stages {
            stage('Test') { steps { sh 'npm test' } }
            stage('Build') { steps { sh 'docker build -t $IMAGE .' } }
            stage('Push') {
              steps {
                withCredentials([usernamePassword(credentialsId: 'registry', usernameVariable: 'U', passwordVariable: 'P')]) {
                  sh 'echo "$P" | docker login $REGISTRY -u "$U" --password-stdin'
                  sh 'docker push $IMAGE'
                }
              }
            }
          }
        }
        """,
        [
            "dev, stage, prod 배포 때마다 이미지를 다시 빌드하는 실수",
            "registry 계정을 개인 계정으로 쓰는 실수",
            "push된 이미지가 어떤 커밋인지 알 수 없는 실수",
        ],
        [
            "Jenkinsfile에 이미지 태그 생성 규칙을 넣어보세요.",
            "Dockerfile label로 Git SHA를 남겨보세요.",
            "테스트 실패 시 이미지가 push되지 않도록 stage 순서를 확인하세요.",
        ],
        [
            "왜 같은 이미지를 환경별로 승격해야 하는가?",
            "이미지 태그에 Git SHA를 넣는 이유는 무엇인가?",
            "registry 인증정보는 어디에 있어야 하는가?",
        ],
    ),
    base_chapter(
        "intermediate", "Kubernetes 배포 Manifest",
        "Kubernetes 배포는 Deployment, Service, ConfigMap, Secret, Ingress 같은 객체의 조합입니다.",
        ["Deployment", "Service", "ConfigMap", "Secret", "Ingress"],
        [
            "Deployment는 Pod 복제와 롤링 업데이트를 담당합니다.",
            "Service는 Pod 앞의 안정적인 네트워크 이름입니다.",
            "ConfigMap과 Secret은 이미지 밖에서 설정을 주입합니다.",
            "Ingress는 외부 HTTP 트래픽을 Service로 연결합니다.",
        ],
        [
            ("분리", "이미지와 설정을 분리하면 같은 이미지를 여러 환경에 배포할 수 있습니다."),
            ("Probe", "readiness와 liveness를 manifest에 포함합니다."),
            ("Resource", "requests와 limits는 운영 매너가 아니라 필수 용량 계약입니다."),
            ("라벨", "app, version, component 같은 라벨 표준을 정합니다."),
        ],
        """
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: app
        spec:
          replicas: 3
          selector:
            matchLabels:
              app: app
          template:
            metadata:
              labels:
                app: app
            spec:
              containers:
                - name: app
                  image: registry.example.com/team/app:gitsha-42
                  ports:
                    - containerPort: 8080
                  readinessProbe:
                    httpGet: { path: /ready, port: 8080 }
                  resources:
                    requests: { cpu: "200m", memory: "256Mi" }
                    limits: { cpu: "1", memory: "512Mi" }
        """,
        [
            "Service selector와 Deployment label을 맞추지 않는 실수",
            "probe와 resources 없이 운영 배포하는 실수",
            "환경별 설정을 이미지에 구워 넣는 실수",
        ],
        [
            "Deployment와 Service를 작성하고 label selector를 맞춰보세요.",
            "이미지 태그만 바꿔 롤링 업데이트를 수행하세요.",
            "readinessProbe 실패 시 트래픽 제외를 확인하세요.",
        ],
        [
            "Kubernetes 배포에 필요한 최소 객체는 무엇인가?",
            "환경별 설정은 어디에 두는 것이 좋은가?",
            "Service가 Pod를 찾는 기준은 무엇인가?",
        ],
    ),
    base_chapter(
        "practical", "Jenkins가 Kubernetes에 배포하는 방식",
        "Jenkins는 kubeconfig나 서비스 계정 권한을 사용해 kubectl, Helm, Kustomize로 클러스터에 변경을 적용합니다.",
        ["Jenkins", "Credential/kubeconfig", "kubectl apply", "Kubernetes API", "Rollout status"],
        [
            "Jenkins가 클러스터에 접근하려면 인증 정보가 필요합니다.",
            "권한은 필요한 namespace와 리소스로 제한해야 합니다.",
            "배포 후 `rollout status`로 성공 여부를 확인해야 합니다.",
            "실패 시 자동 롤백 또는 수동 승인 절차를 설계합니다.",
        ],
        [
            ("권한 최소화", "Jenkins 전용 ServiceAccount를 만들고 namespace 범위 RoleBinding을 사용합니다."),
            ("명령 표준화", "kubectl apply, kustomize build, helm upgrade 중 팀 표준을 정합니다."),
            ("검증", "배포 명령 성공과 애플리케이션 준비 완료는 다릅니다."),
            ("추적", "Deployment annotation에 Jenkins build URL과 Git SHA를 남깁니다."),
        ],
        """
        stage('Deploy to Kubernetes') {
          steps {
            withCredentials([file(credentialsId: 'kubeconfig-dev', variable: 'KUBECONFIG')]) {
              sh 'kubectl -n app set image deployment/app app=$IMAGE'
              sh 'kubectl -n app rollout status deployment/app --timeout=120s'
            }
          }
        }
        """,
        [
            "Jenkins에 cluster-admin 권한을 주는 실수",
            "kubectl 명령 성공만 보고 rollout 상태를 확인하지 않는 실수",
            "운영 배포에 수동 승인이나 변경 기록이 없는 실수",
        ],
        [
            "dev namespace 전용 ServiceAccount 권한을 설계해보세요.",
            "Jenkins에서 kubectl dry-run을 먼저 수행하도록 stage를 추가하세요.",
            "rollout 실패 시 undo하는 절차를 작성하세요.",
        ],
        [
            "Jenkins의 Kubernetes 권한을 최소화해야 하는 이유는 무엇인가?",
            "apply 성공과 rollout 성공은 어떻게 다른가?",
            "배포 이력을 어디에 남길 것인가?",
        ],
    ),
    base_chapter(
        "practical", "환경 승격과 승인",
        "실무 배포는 dev에서 검증한 이미지를 stage, prod로 승격하는 흐름이 안전합니다.",
        ["Dev", "Stage", "Approval", "Prod", "Post-deploy checks"],
        [
            "환경마다 이미지를 다시 빌드하면 같은 코드인지 보장하기 어렵습니다.",
            "승격은 이미 검증된 이미지 태그를 다음 환경에 배포하는 것입니다.",
            "운영 배포 전에는 승인, 변경 티켓, 점검 목록이 필요할 수 있습니다.",
            "배포 후 smoke test와 모니터링 확인이 필요합니다.",
        ],
        [
            ("승인 지점", "Jenkins input step이나 배포 관리 시스템으로 승인 기록을 남깁니다."),
            ("환경 차이", "이미지는 같고 설정만 달라야 합니다."),
            ("릴리즈 노트", "Git commit 목록과 이슈 목록을 자동 생성할 수 있습니다."),
            ("되돌리기", "승격된 이전 이미지 태그를 즉시 배포할 수 있어야 합니다."),
        ],
        """
        stage('Promote to prod') {
          when { branch 'main' }
          steps {
            input message: '운영 배포를 진행할까요?', ok: 'Deploy'
            sh 'kubectl -n prod set image deployment/app app=$IMAGE'
            sh 'kubectl -n prod rollout status deployment/app'
          }
        }
        """,
        [
            "환경마다 새로 빌드해서 dev에서 통과한 이미지와 prod 이미지가 달라지는 실수",
            "승인 기록 없이 운영 배포하는 실수",
            "배포 후 확인 없이 Pipeline을 성공 처리하는 실수",
        ],
        [
            "dev와 prod의 차이를 이미지, 설정, 권한 관점으로 나눠 적으세요.",
            "운영 배포 승인 checklist를 작성하세요.",
            "배포 후 smoke test stage를 추가해보세요.",
        ],
        [
            "승격 배포란 무엇인가?",
            "환경별로 달라져도 되는 것과 달라지면 안 되는 것은 무엇인가?",
            "운영 배포 승인 기록은 왜 중요한가?",
        ],
    ),
    base_chapter(
        "advanced", "GitOps와 다음 단계",
        "GitOps는 클러스터 상태의 기준을 Git 저장소에 두고, 컨트롤러가 클러스터를 그 상태로 맞추는 운영 방식입니다.",
        ["Git desired state", "Review", "GitOps controller", "Cluster sync", "Drift detection"],
        [
            "Jenkins가 직접 kubectl을 실행하는 방식은 push 기반입니다.",
            "GitOps는 클러스터 안의 컨트롤러가 Git을 보고 pull하는 방식입니다.",
            "모든 변경이 Git PR로 남기 때문에 감사와 롤백이 쉬워집니다.",
            "Jenkins는 이미지 빌드와 manifest 업데이트 PR 생성까지 담당하고, 배포는 GitOps가 맡을 수 있습니다.",
        ],
        [
            ("감사성", "운영 상태 변경이 Git 기록으로 남습니다."),
            ("드리프트", "클러스터 실제 상태가 Git과 달라지면 감지할 수 있습니다."),
            ("권한 축소", "Jenkins가 운영 클러스터 직접 권한을 갖지 않아도 됩니다."),
            ("복잡도", "처음부터 GitOps를 도입하기보다 기본 CI/CD가 안정된 뒤 검토해도 됩니다."),
        ],
        """
        1. Jenkins builds image: app:git-a1b2c3d
        2. Jenkins updates manifest repository image tag
        3. Pull request reviews the deployment change
        4. GitOps controller syncs approved desired state
        5. Kubernetes rolls out new Pods
        """,
        [
            "GitOps를 도입했는데 여전히 사람이 kubectl로 운영을 직접 수정하는 실수",
            "애플리케이션 코드 저장소와 배포 manifest 저장소 책임을 정하지 않는 실수",
            "비밀값을 GitOps 저장소에 평문으로 넣는 실수",
        ],
        [
            "현재 push 배포와 GitOps 배포의 장단점을 표로 비교하세요.",
            "이미지 태그 업데이트 PR 흐름을 설계하세요.",
            "운영 직접 수정 금지 정책과 예외 절차를 작성하세요.",
        ],
        [
            "push 기반 배포와 pull 기반 GitOps의 차이는 무엇인가?",
            "GitOps가 감사성에 유리한 이유는 무엇인가?",
            "Jenkins의 역할은 GitOps 도입 후 어떻게 바뀌는가?",
        ],
    ),
]


def expand_with_review_chapters(chapters: list[dict], topic: str) -> list[dict]:
    """Add review, glossary, and operating checklist chapters to make each doc book-like."""
    supplements = make_supplement_chapters(topic)
    glossary = base_chapter(
        "advanced", f"{topic} 용어 사전과 면접식 점검",
        f"{topic}을 실무에서 쓰려면 용어를 외우는 것보다 장애 상황에서 정확히 꺼내 쓸 수 있어야 합니다.",
        ["개념", "증상", "명령", "판단", "개선"],
        [
            "용어는 서로 연결되어 있습니다. 단어 하나를 외우기보다 흐름 안에서 이해하세요.",
            "면접식 질문은 실제 장애 상황에서 생각을 정리하는 연습이 됩니다.",
            "명령어는 결과 해석까지 함께 익혀야 합니다.",
            "운영자는 성공 사례보다 실패 사례에서 더 많이 배웁니다.",
        ],
        [
            ("설명력", "초보자에게 비유로 설명하고, 실무자에게 정확한 계층으로 설명할 수 있어야 합니다."),
            ("진단력", "증상을 보고 어느 계층부터 확인할지 정합니다."),
            ("표준화", "팀에서 같은 용어를 같은 뜻으로 쓰면 장애 대응 속도가 빨라집니다."),
            ("기록", "점검 질문에 대한 답을 팀 위키나 README에 남깁니다."),
        ],
        "",
        [
            "명령어 결과를 보지 않고 암기한 답만 말하는 실수",
            "비슷한 용어를 구분하지 않아 잘못된 계층을 수정하는 실수",
            "팀 안에서 같은 단어를 서로 다른 뜻으로 쓰는 실수",
        ],
        [
            f"{topic} 핵심 용어 20개를 직접 정의해보세요.",
            "장애 상황 3개를 만들고 확인 명령 순서를 적어보세요.",
            "동료에게 5분 설명을 한다고 생각하고 그림을 하나 그려보세요.",
        ],
        [
            "초보자용 비유와 실무자용 정의를 둘 다 말할 수 있는가?",
            "장애 증상에서 확인 순서를 세울 수 있는가?",
            "팀 표준 문서로 남길 내용과 개인 메모로 둘 내용을 구분할 수 있는가?",
        ],
    )
    checklist = base_chapter(
        "advanced", f"{topic} 실무 체크리스트",
        f"마지막 장은 학습 내용을 운영 체크리스트로 압축합니다. 실제 적용 전 이 목록을 훑으면 빠뜨리는 부분을 줄일 수 있습니다.",
        ["설계", "구현", "검증", "배포", "운영"],
        [
            "설계 단계에서는 책임 경계와 실패 방식을 먼저 생각합니다.",
            "구현 단계에서는 최소 권한과 재현성을 지킵니다.",
            "검증 단계에서는 자동 테스트와 수동 점검을 분리합니다.",
            "운영 단계에서는 백업, 롤백, 관찰, 알림이 핵심입니다.",
        ],
        [
            ("문서화", "설치법보다 장애 대응과 롤백 절차가 더 중요해지는 순간이 많습니다."),
            ("소유권", "누가 고치고 누가 승인하는지 정하지 않으면 자동화도 멈춥니다."),
            ("반복 개선", "처음부터 완벽한 플랫폼보다 작은 성공 루프를 여러 번 돌립니다."),
            ("리스크", "새 기술 도입보다 현재 장애 비용을 줄이는 개선이 우선일 때가 많습니다."),
        ],
        "",
        [
            "도구 도입 자체를 목표로 삼는 실수",
            "운영 절차 없이 예제만 복사해 적용하는 실수",
            "롤백과 백업을 배포 후에 생각하는 실수",
        ],
        [
            "체크리스트를 팀 프로젝트에 맞게 삭제/추가하세요.",
            "가장 위험한 항목 3개를 고르고 이번 주 개선 작업으로 쪼개세요.",
            "장애가 났을 때 15분 안에 확인할 대시보드와 명령을 정하세요.",
        ],
        [
            "도구가 아니라 해결하려는 문제가 명확한가?",
            "운영자가 밤에 깨도 따라 할 롤백 절차가 있는가?",
            "학습 환경과 운영 환경의 차이를 알고 있는가?",
        ],
    )
    return chapters + supplements + [glossary, checklist]


def topic_terms(topic: str) -> dict[str, str]:
    if topic == "Docker":
        return {
            "object": "이미지와 컨테이너",
            "command": "docker",
            "unit": "컨테이너",
            "config": "Dockerfile과 compose.yaml",
            "network": "Docker network",
            "secret": "환경변수와 외부 secret",
            "deploy": "이미지 태그와 registry push",
            "debug": "docker logs, inspect, exec",
        }
    if topic == "Jenkins":
        return {
            "object": "Job과 Pipeline",
            "command": "Jenkinsfile",
            "unit": "stage와 build",
            "config": "Jenkinsfile과 Credentials",
            "network": "agent와 외부 시스템 연결",
            "secret": "Jenkins Credentials",
            "deploy": "Pipeline stage와 승인",
            "debug": "console log, stage view, artifacts",
        }
    if topic == "Kubernetes":
        return {
            "object": "Pod와 Deployment",
            "command": "kubectl",
            "unit": "Pod",
            "config": "YAML manifest",
            "network": "Service와 Ingress",
            "secret": "Secret과 RBAC",
            "deploy": "rollout과 rollback",
            "debug": "kubectl describe, logs, events",
        }
    return {
        "object": "이미지, Pipeline, Kubernetes 객체",
        "command": "docker, Jenkinsfile, kubectl",
        "unit": "빌드 산출물과 배포 단위",
        "config": "Dockerfile, Jenkinsfile, manifest",
        "network": "registry, agent, Service, Ingress",
        "secret": "Credentials, kubeconfig, Secret",
        "deploy": "CI/CD 배포 흐름",
        "debug": "Jenkins log, docker inspect, kubectl events",
    }


def make_supplement_chapters(topic: str) -> list[dict]:
    t = topic_terms(topic)
    return [
        base_chapter(
            "beginner", "4주 학습 로드맵",
            f"{topic}은 하루 만에 외우는 도구가 아니라, 작은 실습을 반복하며 감각을 쌓는 영역입니다. 이 장은 처음 보는 사람이 한 달 동안 따라갈 수 있는 순서입니다.",
            ["1주차 개념", "2주차 로컬 실습", "3주차 자동화", "4주차 운영 시나리오"],
            [
                f"1주차에는 {t['object']}의 이름과 책임을 구분합니다.",
                f"2주차에는 {t['command']}를 손으로 실행하며 성공과 실패 결과를 관찰합니다.",
                f"3주차에는 {t['config']}를 저장소에 넣고 반복 가능한 형태로 만듭니다.",
                "4주차에는 일부러 장애를 만들고 원인을 찾는 연습을 합니다.",
            ],
            [
                ("학습 단위", "하루에 많은 명령을 외우기보다, 한 개념을 성공과 실패 양쪽으로 실험합니다."),
                ("기록", "명령어보다 결과 해석을 적어야 다음 장애 때 도움이 됩니다."),
                ("반복", "같은 실습을 다른 포트, 다른 이름, 다른 환경변수로 다시 실행해보면 구조가 보입니다."),
                ("실무 전환", "개인 실습이 끝나면 팀 표준과 보안 정책으로 확장합니다."),
            ],
            "",
            [
                "처음부터 운영 환경을 만지며 배우는 실수",
                "명령어만 복사하고 결과를 해석하지 않는 실수",
                "성공 경로만 따라가서 장애 상황에 약해지는 실수",
            ],
            [
                "매일 30분씩 한 장을 읽고, 반드시 한 번은 실패 상황을 만들어보세요.",
                "실습 노트에 입력 명령, 기대 결과, 실제 결과, 배운 점을 적으세요.",
                "4주차 마지막에는 작은 서비스 하나를 처음부터 운영 흐름까지 연결하세요.",
            ],
            [
                "오늘 배운 개념을 그림으로 그릴 수 있는가?",
                "성공 로그와 실패 로그의 차이를 설명할 수 있는가?",
                "다음 주에 다시 봐도 이해될 만큼 실습 기록이 남아 있는가?",
            ],
        ),
        base_chapter(
            "basic", "명령어를 읽는 법",
            f"{topic} 명령어는 외울 대상이 아니라 질문의 형식입니다. 무엇을 보고 싶은지, 무엇을 바꾸려는지 먼저 정해야 합니다.",
            ["질문", "명령", "출력", "해석", "다음 행동"],
            [
                "명령을 실행하기 전에 내가 확인하려는 대상을 먼저 말합니다.",
                "출력은 상태, 원인, 다음 단서로 나누어 읽습니다.",
                "옵션은 결과 형식을 바꾸거나 범위를 좁히는 역할을 합니다.",
                "좋은 운영자는 긴 명령을 많이 아는 사람이 아니라 출력에서 다음 질문을 뽑는 사람입니다.",
            ],
            [
                ("상태 조회", f"{t['debug']} 같은 조회 명령으로 현재 상태를 확인합니다."),
                ("변경 명령", "변경 명령은 되돌릴 방법을 알고 실행합니다."),
                ("범위 제한", "namespace, job, service, container처럼 범위를 좁히면 사고를 줄입니다."),
                ("로그 보존", "중요한 장애 출력은 캡처하거나 이슈에 남깁니다."),
            ],
            "",
            [
                "명령어를 실행한 뒤 출력의 핵심 줄을 읽지 않는 실수",
                "조회 명령과 변경 명령을 구분하지 않는 실수",
                "운영에서 범위를 지정하지 않은 명령을 습관적으로 실행하는 실수",
            ],
            [
                f"{t['debug']}에 해당하는 명령을 하나 골라 출력 항목을 줄별로 해석하세요.",
                "같은 대상을 기본 출력, 상세 출력, JSON/YAML 출력으로 각각 확인하세요.",
                "변경 명령을 실행하기 전 백업 또는 되돌리기 명령을 먼저 적어보세요.",
            ],
            [
                "이 명령이 조회인지 변경인지 즉시 구분할 수 있는가?",
                "출력에서 정상과 비정상을 가르는 기준을 알고 있는가?",
                "명령 실행 범위를 안전하게 좁혔는가?",
            ],
        ),
        base_chapter(
            "basic", "로컬 실습 환경 만들기",
            f"로컬 실습 환경은 {topic}을 안전하게 망가뜨려보는 공간입니다. 운영에서 해서는 안 되는 실험을 여기서 반복하세요.",
            ["설치", "샘플 실행", "관찰", "삭제", "재생성"],
            [
                "처음에는 최소 예제로 시작합니다.",
                "실행한 뒤 바로 삭제하고 다시 만드는 연습을 합니다.",
                "로컬 환경의 상태를 초기화하는 방법을 알아야 실습이 막히지 않습니다.",
                "실무와 똑같지 않아도 개념을 익히기에는 충분합니다.",
            ],
            [
                ("격리", "개인 PC의 실습과 회사 운영 계정을 섞지 않습니다."),
                ("버전", "설치한 도구 버전을 기록합니다."),
                ("초기화", "잘못 꼬였을 때 어디까지 지워도 되는지 알아둡니다."),
                ("샘플", "작은 HTTP 서버 하나를 기준 예제로 삼으면 비교가 쉽습니다."),
            ],
            "",
            [
                "실습 계정과 운영 계정을 같은 context로 섞는 실수",
                "버전을 기록하지 않아 나중에 결과가 달라지는 실수",
                "삭제와 재생성을 연습하지 않아 환경이 꼬였을 때 멈추는 실수",
            ],
            [
                "현재 설치된 관련 도구 버전을 기록하세요.",
                "샘플 서비스를 실행하고 브라우저 또는 로그로 확인하세요.",
                "샘플을 삭제한 뒤 같은 절차로 다시 만들어보세요.",
            ],
            [
                "실습 환경을 초기 상태로 되돌릴 수 있는가?",
                "운영 계정과 실습 계정을 분리했는가?",
                "실습 결과가 예상과 다를 때 확인할 첫 명령을 알고 있는가?",
            ],
        ),
        base_chapter(
            "intermediate", "네트워크 문제를 좁히는 법",
            f"{topic} 실무 장애에서 네트워크 문제는 매우 흔합니다. 이름 해석, 포트, 라우팅, 방화벽, 애플리케이션 바인딩 주소를 순서대로 봅니다.",
            ["이름 해석", "포트", "라우팅", "방화벽", "앱 설정"],
            [
                "먼저 목적지 이름이 올바른 주소로 해석되는지 확인합니다.",
                "다음은 목적지 포트가 열려 있고 프로세스가 듣고 있는지 확인합니다.",
                "그 다음 요청이 어느 네트워크 경로를 지나가는지 봅니다.",
                "마지막으로 애플리케이션이 `localhost`에만 바인딩되어 외부에서 못 받는지 확인합니다.",
            ],
            [
                ("계층 분리", f"{t['network']} 계층과 애플리케이션 계층을 분리해 봅니다."),
                ("내부/외부", "내부 통신 성공과 외부 접근 성공은 다른 문제입니다."),
                ("로그 비교", "클라이언트 로그, 프록시 로그, 서버 로그의 시간이 맞는지 봅니다."),
                ("변경 이력", "최근 DNS, 포트, 인증서, 방화벽 변경을 확인합니다."),
            ],
            "",
            [
                "`localhost`의 의미를 환경마다 다르게 해석하지 못하는 실수",
                "포트가 열렸는지 확인하지 않고 코드만 고치는 실수",
                "외부 노출 문제를 내부 서비스 문제로 착각하는 실수",
            ],
            [
                "내부에서는 되지만 외부에서는 안 되는 상황을 일부러 만들어보세요.",
                "이름 해석, 포트, 라우팅, 앱 로그 순서로 확인표를 채우세요.",
                "정상 요청과 실패 요청의 로그 시간을 나란히 비교하세요.",
            ],
            [
                "내부 통신과 외부 접근을 구분해 설명할 수 있는가?",
                "포트 문제와 애플리케이션 오류를 어떻게 구분할 것인가?",
                "최근 변경 이력을 어디서 확인할 것인가?",
            ],
        ),
        base_chapter(
            "intermediate", "비밀값과 권한 사고방식",
            f"{topic}에서 비밀값은 편하게 쓰는 값이 아니라 유출되면 회수 비용이 생기는 자산입니다.",
            ["비밀 생성", "안전한 저장", "실행 시 주입", "로그 마스킹", "회전"],
            [
                "비밀값은 코드 저장소와 이미지에 넣지 않습니다.",
                "필요한 실행 시점과 필요한 범위에만 주입합니다.",
                "로그, 에러 메시지, 디버그 출력에 값이 찍히지 않게 합니다.",
                "유출을 전제로 교체 절차와 만료 정책을 둡니다.",
            ],
            [
                ("최소 권한", f"{t['secret']}은 필요한 사용자와 작업에만 허용합니다."),
                ("분리", "개발, 스테이징, 운영 비밀값을 분리합니다."),
                ("회전", "토큰과 인증서는 정기 교체가 가능해야 합니다."),
                ("감사", "누가 어떤 비밀값을 사용했는지 추적 가능해야 합니다."),
            ],
            "",
            [
                "예제 편의상 넣은 비밀번호를 실제 저장소에 커밋하는 실수",
                "로그 마스킹을 믿고 명령 전체를 무분별하게 출력하는 실수",
                "운영 비밀값을 개발 환경에서도 그대로 쓰는 실수",
            ],
            [
                "현재 프로젝트에서 비밀값 후보를 모두 찾아 목록화하세요.",
                "각 비밀값의 저장 위치, 사용 위치, 회전 방법을 적으세요.",
                "로그에 값이 노출될 수 있는 명령을 찾아 수정하세요.",
            ],
            [
                "이 값이 유출되면 무엇을 교체해야 하는가?",
                "누가 이 값을 읽거나 사용할 수 있는가?",
                "개발과 운영 비밀값이 분리되어 있는가?",
            ],
        ),
        base_chapter(
            "practical", "관찰 가능성: 로그, 지표, 이벤트",
            f"{topic}을 실무에서 쓴다는 것은 문제가 생겼을 때 내부 상태를 볼 수 있다는 뜻입니다.",
            ["Logs", "Metrics", "Events", "Traces", "Alerts"],
            [
                "로그는 특정 요청이나 작업의 이야기를 보여줍니다.",
                "지표는 시스템의 흐름과 추세를 보여줍니다.",
                "이벤트는 플랫폼이 내린 판단과 상태 변화를 보여줍니다.",
                "알림은 사람이 봐야 할 순간을 알려주지만 너무 많으면 무시됩니다.",
            ],
            [
                ("상관관계", "배포 시각, 에러율, 지연시간, 리소스 사용량을 함께 봅니다."),
                ("보존", "장애 후 분석이 가능하도록 로그 보존 기간을 정합니다."),
                ("대시보드", "평소에도 보는 대시보드와 장애 때 보는 대시보드를 구분합니다."),
                ("알림 품질", "조치할 수 없는 알림은 줄이고, 조치 링크를 포함합니다."),
            ],
            "",
            [
                "성공 로그만 남기고 실패 원인을 남기지 않는 실수",
                "CPU, 메모리, 지연시간 같은 기본 지표 없이 운영하는 실수",
                "알림이 너무 많아 실제 장애를 놓치는 실수",
            ],
            [
                "샘플 서비스에 요청 ID를 로그로 남기는 방식을 설계하세요.",
                "장애 시 볼 대시보드 항목 5개를 정하세요.",
                "배포 직후 확인할 지표와 30분 뒤 확인할 지표를 나누세요.",
            ],
            [
                "로그와 지표는 각각 어떤 질문에 답하는가?",
                "알림을 받았을 때 바로 취할 행동이 명확한가?",
                "배포와 장애를 시간축에서 연결해 볼 수 있는가?",
            ],
        ),
        base_chapter(
            "practical", "성능과 용량 계획",
            f"{topic}에서 성능 문제는 단순히 빠르게 만드는 일이 아니라 어느 자원이 병목인지 찾는 일입니다.",
            ["요청량", "CPU", "Memory", "I/O", "Queue", "Scale"],
            [
                "먼저 시스템이 처리해야 하는 요청량을 정의합니다.",
                "CPU 병목, 메모리 부족, 디스크 I/O, 네트워크, 외부 API 대기를 구분합니다.",
                "큐가 쌓이는 곳은 병목의 위치를 알려줍니다.",
                "확장은 수평 확장과 수직 확장, 캐시, 비동기화 중 무엇이 맞는지 판단해야 합니다.",
            ],
            [
                ("측정 우선", "측정 없는 튜닝은 운에 가깝습니다."),
                ("한 번에 하나", "한 번에 하나의 변수만 바꿔야 원인을 알 수 있습니다."),
                ("피크", "평균보다 피크 시간대와 장애 시나리오가 중요합니다."),
                ("비용", "성능 개선은 인프라 비용과 운영 복잡도를 함께 봅니다."),
            ],
            "",
            [
                "CPU만 보고 모든 성능 문제를 판단하는 실수",
                "평균 지표만 보고 피크 장애를 놓치는 실수",
                "캐시를 넣고 무효화 전략을 설계하지 않는 실수",
            ],
            [
                "샘플 서비스에 부하를 주고 CPU, 메모리, 응답시간 변화를 기록하세요.",
                "병목 후보를 세 개 적고 각각 확인할 지표를 매핑하세요.",
                "확장 전후 비용과 복잡도 변화를 적어보세요.",
            ],
            [
                "현재 병목이 CPU인지 대기 시간인지 어떻게 확인할 것인가?",
                "평균과 p95, p99 지표의 차이는 무엇인가?",
                "확장보다 코드 수정이 나은 경우는 언제인가?",
            ],
        ),
        base_chapter(
            "practical", "운영 변경 절차",
            f"{topic} 실무 변경은 명령 한 줄이 아니라 계획, 실행, 확인, 롤백의 절차입니다.",
            ["변경 계획", "사전 점검", "실행", "검증", "롤백 또는 완료"],
            [
                "변경 전에 무엇이 바뀌는지와 영향 범위를 적습니다.",
                "실행 전에 현재 상태를 캡처합니다.",
                "실행 중에는 한 번에 하나씩 바꾸고 결과를 확인합니다.",
                "실패하면 정해둔 롤백 절차로 되돌립니다.",
            ],
            [
                ("변경 창", "사용자가 적은 시간이나 배포 창을 정합니다."),
                ("승인", "운영 영향이 있으면 승인과 기록을 남깁니다."),
                ("검증", "명령 성공이 아니라 사용자 관점 성공을 확인합니다."),
                ("커뮤니케이션", "시작, 진행, 완료, 실패를 이해관계자에게 알립니다."),
            ],
            "",
            [
                "롤백 방법을 모른 채 변경을 시작하는 실수",
                "변경 전 상태를 기록하지 않아 비교할 수 없는 실수",
                "명령이 성공했다는 이유로 실제 서비스 확인을 생략하는 실수",
            ],
            [
                "작은 변경 하나를 골라 변경 계획서를 써보세요.",
                "사전 상태 캡처 명령과 사후 검증 명령을 정하세요.",
                "실패 시 되돌리는 명령 또는 절차를 미리 적으세요.",
            ],
            [
                "이 변경의 영향 범위는 어디까지인가?",
                "변경 전 정상 상태를 증명할 자료가 있는가?",
                "롤백 기준과 롤백 방법이 명확한가?",
            ],
        ),
        base_chapter(
            "advanced", "장애 시나리오 워크북",
            f"이 장은 {topic} 장애를 일부러 만들어보고 복구하는 워크북입니다. 실무 감각은 정상 예제보다 실패 예제에서 훨씬 빨리 자랍니다.",
            ["장애 주입", "증상 관찰", "원인 가설", "증거 수집", "복구", "회고"],
            [
                "장애를 만들기 전에 정상 상태를 캡처합니다.",
                "장애가 발생하면 증상을 사용자 관점과 시스템 관점으로 나눕니다.",
                "가설을 세우고 증거로 확인합니다.",
                "복구 후에는 왜 예방하지 못했는지 회고합니다.",
            ],
            [
                ("실습 안전", "운영이 아닌 로컬 또는 테스트 환경에서만 수행합니다."),
                ("시간 제한", "15분 안에 1차 원인 후보를 찾는 연습을 합니다."),
                ("기록", "명령과 출력의 핵심 줄을 남깁니다."),
                ("재발 방지", "문서, 알림, 테스트, 권한 중 하나 이상의 개선으로 연결합니다."),
            ],
            "",
            [
                "복구만 하고 회고와 예방 조치를 남기지 않는 실수",
                "가설 없이 명령을 무작위로 실행하는 실수",
                "정상 상태 캡처가 없어 무엇이 바뀌었는지 모르는 실수",
            ],
            [
                f"{t['config']}에서 일부러 잘못된 값을 넣어 실패를 만드세요.",
                f"{t['debug']}로 증거를 수집하고 원인 후보를 세우세요.",
                "복구 후 재발 방지 항목을 하나 작성하세요.",
            ],
            [
                "증상과 원인을 구분해 적었는가?",
                "가설을 증거로 확인했는가?",
                "재발 방지 조치가 실제로 실행 가능한가?",
            ],
        ),
        base_chapter(
            "advanced", "최종 프로젝트",
            f"마지막 실습은 {topic}을 단독 지식이 아니라 실제 서비스 운영 흐름 안에서 써보는 것입니다.",
            ["요구사항", "구성", "자동화", "배포", "장애 대응 문서"],
            [
                "작은 웹 서비스를 하나 정합니다.",
                f"{t['config']}로 실행 구성을 코드화합니다.",
                "자동 검증과 배포 또는 재생성 절차를 문서화합니다.",
                "장애 대응 명령과 롤백 절차를 README에 넣습니다.",
            ],
            [
                ("완성 기준", "기능 동작보다 재현 가능한 실행과 복구가 기준입니다."),
                ("동료 검증", "다른 사람이 README만 보고 실행할 수 있어야 합니다."),
                ("운영성", "로그, 설정, 비밀값, 데이터 위치가 설명되어야 합니다."),
                ("확장", "다음 단계로 CI, registry, Kubernetes 또는 GitOps와 연결합니다."),
            ],
            "",
            [
                "내 PC에서만 되는 프로젝트를 완성으로 착각하는 실수",
                "README가 명령어 나열만 있고 장애 대응이 없는 실수",
                "비밀값과 환경별 설정을 프로젝트에 섞어두는 실수",
            ],
            [
                "작은 HTTP API 또는 정적 웹 앱을 기준 서비스로 정하세요.",
                "처음 실행, 변경 반영, 삭제, 재생성, 롤백 절차를 모두 작성하세요.",
                "동료 또는 미래의 내가 30분 안에 따라 할 수 있는지 검증하세요.",
            ],
            [
                "저장소만 보고 실행과 배포 흐름을 이해할 수 있는가?",
                "장애가 났을 때 확인 명령과 롤백 절차가 있는가?",
                "비밀값과 데이터가 안전한 위치에 있는가?",
            ],
        ),
    ]


def write_index(root: Path, files: list[tuple[str, Path, str]]) -> None:
    links = "".join(
        f'<div class="card"><strong>{esc(title)}</strong><p>{esc(desc)}</p><a href="{esc(path.as_posix())}">열기</a></div>'
        for title, path, desc in files
    )
    doc = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DevOps 학습자료 인덱스</title>
  <style>{STYLE}</style>
</head>
<body>
  <main>
    <section class="hero">
      <span class="badge">DevOps Learning Materials</span>
      <h1>Docker, Jenkins, Kubernetes 학습자료</h1>
      <p>각 문서는 초보자 관점에서 출발해 실무 운영 판단까지 올라가는 바텀업 HTML 교재입니다. 브라우저에서 열고, 필요하면 인쇄 또는 PDF 저장으로 읽어도 좋습니다.</p>
      <div class="grid">{links}</div>
    </section>
  </main>
</body>
</html>
"""
    (root / "index.html").write_text(doc, encoding="utf-8")


def main() -> None:
    downloads = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"
    root = downloads / "DevOps-Learning-Materials"
    outputs = [
        ("Docker", root / "Docker" / "docker-learning.html", "컨테이너, 이미지, Dockerfile, Compose, 보안과 운영 디버깅"),
        ("Jenkins", root / "Jenkins" / "jenkins-learning.html", "CI/CD, Pipeline as Code, Credentials, Docker 연동, 운영 관리"),
        ("Kubernetes", root / "Kubernetes" / "kubernetes-learning.html", "Pod, Deployment, Service, ConfigMap, Secret, Storage, 운영 디버깅"),
        ("Docker-Jenkins-Kubernetes Integration", root / "Integration" / "integration-learning.html", "이미지 빌드부터 Kubernetes 배포와 GitOps까지 이어지는 전체 흐름"),
    ]
    render_doc(
        "Docker 바텀업 학습 교재",
        "컨테이너를 처음 접하는 사람부터 Dockerfile과 Compose를 실무에서 운영하는 사람까지 이어지는 학습 자료입니다.",
        expand_with_review_chapters(DOCKER, "Docker"),
        SOURCES["Docker"],
        outputs[0][1],
    )
    render_doc(
        "Jenkins 바텀업 학습 교재",
        "CI/CD 자동화의 이유에서 시작해 Pipeline, Credentials, Docker 빌드, Jenkins 운영까지 단계적으로 설명합니다.",
        expand_with_review_chapters(JENKINS, "Jenkins"),
        SOURCES["Jenkins"],
        outputs[1][1],
    )
    render_doc(
        "Kubernetes 바텀업 학습 교재",
        "컨테이너 오케스트레이션의 필요성에서 시작해 Deployment, Service, 설정, 저장소, 장애 대응까지 다룹니다.",
        expand_with_review_chapters(KUBERNETES, "Kubernetes"),
        SOURCES["Kubernetes"],
        outputs[2][1],
    )
    render_doc(
        "Docker + Jenkins + Kubernetes 연동 교재",
        "Docker가 포장하고 Jenkins가 검증하며 Kubernetes가 실행하는 전체 실무 배포 흐름을 하나로 연결합니다.",
        expand_with_review_chapters(INTEGRATION, "통합 DevOps"),
        SOURCES["Docker"] + SOURCES["Jenkins"] + SOURCES["Kubernetes"],
        outputs[3][1],
    )
    write_index(root, [(title, path.relative_to(root), desc) for title, path, desc in outputs])
    print(root)
    for _, path, _ in outputs:
        print(path)


if __name__ == "__main__":
    main()
