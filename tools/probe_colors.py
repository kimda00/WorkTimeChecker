# -*- coding: utf-8 -*-
"""다우오피스 캘린더 색상 팔레트(번호->hex) 추출용 일회성 탐침."""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import ehr

ORIGIN = ehr.ORIGIN
STATE = ehr.STATE
OUT = os.path.join(BASE, "tools", "probe_colors_out.json")

JS = r"""
() => {
  const found = {};
  // 1) 모든 CSS 규칙 훑어서 selector 안 숫자 + background-color 수집
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch(e) { continue; }
    if (!rules) continue;
    for (const r of rules) {
      if (!r.selectorText || !r.style) continue;
      const bg = r.style.backgroundColor || r.style.background || r.style.borderColor || r.style.color;
      if (!bg) continue;
      // color1 / color-1 / cal_color_1 / calColor1 등에서 숫자 추출
      const m = r.selectorText.match(/color[-_]?(\d{1,2})\b/i);
      if (m) {
        const n = m[1];
        (found[n] = found[n] || []).push({sel: r.selectorText, bg});
      }
    }
  }
  return found;
}
"""


def run(headless):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = ehr._launch(p, headless=headless)
        kw = {"storage_state": STATE} if os.path.exists(STATE) else {}
        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, **kw)
        page = ctx.new_page()
        try:
            page.goto(ORIGIN + "/app/calendar", wait_until="networkidle", timeout=60000)
        except Exception:
            pass
        time.sleep(5)
        try:
            data = page.evaluate(JS)
        except Exception as e:
            data = {"error": str(e)}
        # 색 편집 팔레트를 강제로 찾기 위해 한번 더: 인라인 style 가진 요소들
        try:
            inline = page.evaluate(r"""() => {
              const out=[];
              document.querySelectorAll('[class*=color]').forEach(el=>{
                const cs=getComputedStyle(el);
                const cls=el.className.toString();
                const m=cls.match(/color[-_]?(\d{1,2})\b/i);
                if(m) out.push({n:m[1], cls, bg:cs.backgroundColor, color:cs.color, border:cs.borderColor});
              });
              return out.slice(0,200);
            }""")
        except Exception as e:
            inline = [{"error": str(e)}]
        ctx.close(); browser.close()
    return {"cssRules": data, "inline": inline}


if __name__ == "__main__":
    res = run(headless=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    # 요약 출력: 번호 -> 대표 색
    print("=== css rules ===")
    css = res.get("cssRules") or {}
    if isinstance(css, dict):
        for n in sorted(css, key=lambda x: int(x) if str(x).isdigit() else 99):
            for e in css[n][:3]:
                print(" ", n, e.get("bg"), "|", e.get("sel")[:70])
    print("=== inline (num -> bg/color) ===")
    seen = {}
    for it in (res.get("inline") or []):
        if "n" in it and it["n"] not in seen:
            seen[it["n"]] = it
            print(" ", it["n"], "bg=", it.get("bg"), "color=", it.get("color"), "|", it.get("cls")[:50])
    print(">> saved", OUT)
