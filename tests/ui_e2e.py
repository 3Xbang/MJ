"""End-to-end browser test of the web UI against tests/ui_mock_server.py (no GPU needed).

    python tests/ui_e2e.py            # needs: pip install playwright ; Google Chrome installed
Screenshots are written to the folder given by AFE_SHOTS (default: temp dir).
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

PORT = 8197
HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.environ.get("AFE_SHOTS") or tempfile.mkdtemp(prefix="afe_shots_")
os.makedirs(SHOTS, exist_ok=True)
URL = f"http://127.0.0.1:{PORT}/afe/"
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""), flush=True)


def wait_server():
    for _ in range(80):
        try:
            urllib.request.urlopen(URL, timeout=1)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("mock server did not start")


def wait_idle(page, timeout=60000):
    """Dock disappears or shows a final state (ok / err)."""
    page.wait_for_function(
        "() => { const d = document.querySelector('#dock'); "
        "return d.classList.contains('hidden') || d.classList.contains('ok') || d.classList.contains('err'); }",
        timeout=timeout)


def main():
    env = dict(os.environ, AFE_MOCK_DELAY="0.2", PYTHONIOENCODING="utf-8")
    env["AFE_MOCK_OUT"] = tempfile.mkdtemp(prefix="afe_out_")
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "ui_mock_server.py"), str(PORT)], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        wait_server()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            # expected failures (empty-script 400, browser favicon 404) are not JavaScript errors
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

            page.goto(URL)
            page.wait_for_selector("#stepper .step-chip")
            check("page loads, 5 steps shown", page.locator("#stepper .step-chip").count() == 5)
            check("test mode banner visible by default", "试跑模式已开启" in page.inner_text("#banner"))
            page.screenshot(path=f"{SHOTS}/01_start.png")

            # step 1 — failure path first (needs a script)
            page.click("button[data-act=run][data-stage='1']")
            page.wait_for_selector("#dock.err")
            check("empty script -> friendly error", "粘贴剧本" in page.inner_text("#dockMsg"))
            page.click("#dockClose")

            page.fill("textarea[data-set=script]", "【场景A：超市】阿明在柜台整理货物。FAIL")
            page.click("button[data-act=run][data-stage='1']")
            page.wait_for_selector("#dock.err", timeout=30000)
            check("backend failure -> friendly message", "显存不足" in page.inner_text("#dockMsg"), page.inner_text("#dockMsg"))
            page.click("#dockClose")

            page.fill("textarea[data-set=script]", "【场景A：超市】阿明在柜台整理货物。\n【场景B：公寓】小红在看电视。")
            page.click("button[data-act=run][data-stage='1']")
            page.wait_for_selector("#dock:not(.hidden)")
            check("progress dock appears while running", page.locator("#dock").is_visible() and page.inner_text("#dockMsg").strip() != "")
            wait_idle(page)
            page.wait_for_selector(".chips .chip")
            chips = page.inner_text(".chips")
            check("analysis summary shown", "6 个分镜" in chips and "2 个角色" in chips, chips.replace("\n", " "))
            check("shot table has 6 rows", page.locator(".table-wrap tr").count() == 7)
            page.screenshot(path=f"{SHOTS}/02_step1_done.png", full_page=True)
            page.click(".tabs button[data-tab=cast]")
            check("cast tab lists characters", "阿明" in page.inner_text(".table-wrap"))

            # step 2
            check("step 2 button enabled after analysis", page.locator("button[data-act=run][data-stage='2']").is_enabled())
            page.click("button[data-act=run][data-stage='2']")
            page.wait_for_selector("#dock:not(.hidden)")
            wait_idle(page)
            page.wait_for_selector(".card[data-step='2'] .group")
            check("2 scene groups x 3 views", page.locator(".card[data-step='2'] input[data-sel=scene]").count() == 6)
            check("cast candidates 3 each", page.locator(".card[data-step='2'] input[data-sel=cast]").count() == 6)
            check("props images shown", page.locator(".card[data-step='2'] .group:last-child img").count() >= 1)
            srcs = page.evaluate("() => [...document.querySelectorAll('.card[data-step=\"2\"] img')].map(i => i.src)")
            bad = [u for u in srcs if page.request.get(u).status != 200]
            check("all step-2 image URLs load", srcs and not bad, f"{len(srcs)} images, bad={bad[:2]}")
            page.locator(".card[data-step='2'] label.pick:has(input[data-sel=scene][data-id='1'][data-val='2'])").click()
            page.locator(".card[data-step='2'] label.pick:has(input[data-sel=cast][data-id='2'][data-val='3'])").click()
            page.screenshot(path=f"{SHOTS}/03_step2_done.png", full_page=True)
            st = page.evaluate("() => ({scene: S.settings.scene_view_picks, cast: S.settings.cast_picks})")
            check("picks stored as settings", st["scene"] == "1:2" and st["cast"] == "2:3", str(st))

            # step 3 (test mode => 2 shots)
            page.fill("select[data-set=kf_variants]", "") if False else page.select_option("select[data-set=kf_variants]", "2")
            page.click("button[data-act=run][data-stage='3']")
            wait_idle(page)
            page.wait_for_selector(".card[data-step='3'] .shot")
            check("test mode: only 2 keyframes", page.locator(".card[data-step='3'] .shot").count() == 2)
            check("2 versions per shot offered", page.locator(".card[data-step='3'] input[data-sel=kf]").count() == 4)
            page.screenshot(path=f"{SHOTS}/04_step3_done.png", full_page=True)
            page.locator(".card[data-step='3'] label.pick:has(input[data-sel=kf][data-id='shot_001'][data-val='2'])").click()
            check("kf pick stored", page.evaluate("() => S.settings.kf_picks") == "shot_001:2")

            # step 4
            page.click("button[data-act=run][data-stage='4']")
            wait_idle(page, 90000)
            page.wait_for_selector(".card[data-step='4'] video")
            check("2 clips rendered", page.locator(".card[data-step='4'] video").count() == 2)
            page.fill(".card[data-step='4'] input[data-long='shot_001']", "10")
            page.dispatch_event(".card[data-step='4'] input[data-long='shot_001']", "change")
            check("long take stored", page.evaluate("() => S.settings.long_takes") == "shot_001:10")
            page.locator(".card[data-step='4'] input[data-skip='shot_002']").click()
            check("skip stored", page.evaluate("() => S.settings.skip_shots") == "shot_002")
            page.screenshot(path=f"{SHOTS}/05_step4_done.png", full_page=True)

            # re-render only changed shot (long take on shot_001)
            page.click("button[data-act=run][data-stage='4']")
            wait_idle(page, 90000)
            check("re-run after long-take edit succeeds", "完成" in page.inner_text("#dockMsg"), page.inner_text("#dockMsg"))

            # step 5
            page.click("button[data-act=run][data-stage='5']")
            wait_idle(page, 60000)
            page.wait_for_selector(".card[data-step='5'] .movie video")
            check("final movie shown", page.locator(".card[data-step='5'] .movie video").count() == 1)
            check("download link present", page.locator(".card[data-step='5'] a[download]").count() == 1)
            page.screenshot(path=f"{SHOTS}/06_step5_done.png", full_page=True)

            # persistence: reload page, state is restored from the server
            page.reload()
            page.wait_for_selector("#stepper .step-chip")
            page.wait_for_selector(".card[data-step='5'] .movie video", state="attached")
            check("after reload: movie + picks restored",
                  page.evaluate("() => S.settings.scene_view_picks") == "1:2" and
                  page.locator("#stepper .step-chip.done").count() == 5)
            check("after reload: script restored", "小红在看电视" in page.input_value("textarea[data-set=script]"))

            # cancel
            page.evaluate("() => { S.open[2] = true; render(); }")
            page.click("button[data-act=redo-cast][data-char='1']")
            page.wait_for_selector("#dock:not(.hidden)")
            page.click("#dockCancel")
            wait_idle(page, 30000)
            check("cancel returns a friendly message", "已取消" in page.inner_text("#dockMsg") or "完成" in page.inner_text("#dockMsg"),
                  page.inner_text("#dockMsg"))

            check("no JavaScript errors", not errors, "; ".join(errors[:3]))
            browser.close()
    finally:
        srv.terminate()
        try:
            out = srv.stdout.read().decode("utf-8", errors="replace")
            if "Traceback" in out or "error" in out.lower():
                print("--- server log ---\n" + out[-2500:])
        except Exception:
            pass
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed. Screenshots: {SHOTS}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
