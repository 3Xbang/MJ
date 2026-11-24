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
            page.evaluate("() => { S.open[2] = true; render(); }")
            check("reference upload entry is visible even before the script is analysed",
                  page.locator(".card[data-step='2'] details.refs summary").is_visible())
            check("... with an explanation that it is optional",
                  "不上传也完全没问题" in page.inner_text(".card[data-step='2'] details.refs"))
            check("version label shown in the header", "版本" in page.inner_text("#ver"), page.inner_text("#ver"))
            page.evaluate("() => { S.open = {1: true}; render(); }")
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

            page.fill("input[data-set=duration]", "30")
            page.fill("textarea[data-set=script]", "【场景 A：超市】阿明整理货物。阿明放下箱子。阿明查看手机。阿明继续工作。\n【场景 B：公寓】小红看电视。小红关掉电视。")
            page.click("button[data-act=run][data-stage='1']")
            page.wait_for_selector("#dock:not(.hidden)")
            check("progress dock appears while running", page.locator("#dock").is_visible() and page.inner_text("#dockMsg").strip() != "")
            wait_idle(page)
            # Batch analysis pauses after each small batch. Continue until the
            # server publishes the complete analysis, without re-running done batches.
            for _ in range(4):
                if page.locator(".chips .chip").count():
                    break
                page.click("button[data-act=continue-analysis]")
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

            # the right-hand panel mirrors exactly what is selected on the left
            base = lambda u: (u or "").split("&t=")[0]
            check("sidebar lists 2 scene + 2 character selections", page.locator("#side .sel").count() == 4,
                  str(page.locator("#side .sel").count()))
            med1 = page.get_attribute(".card[data-step='2'] input[data-sel=scene][data-id='1'][data-val='2'] ~ img", "src")
            side_scene1 = page.locator("#side .sel img").nth(0).get_attribute("src")
            check("sidebar shows the chosen scene view (scene 1 = medium)", base(med1) == base(side_scene1), f"{base(med1)} vs {base(side_scene1)}")
            v3 = page.get_attribute(".card[data-step='2'] input[data-sel=cast][data-id='2'][data-val='3'] ~ img", "src")
            side_char2 = page.locator("#side .sel img").nth(3).get_attribute("src")
            check("sidebar shows the chosen character version (char 2 = v3)", base(v3) == base(side_char2), f"{base(v3)} vs {base(side_char2)}")
            page.locator(".card[data-step='2'] label.pick:has(input[data-sel=cast][data-id='2'][data-val='1'])").click()
            side_char2 = page.locator("#side .sel img").nth(3).get_attribute("src")
            v1 = page.get_attribute(".card[data-step='2'] input[data-sel=cast][data-id='2'][data-val='1'] ~ img", "src")
            check("sidebar follows a changed selection immediately", base(v1) == base(side_char2))
            page.locator(".card[data-step='2'] label.pick:has(input[data-sel=cast][data-id='2'][data-val='3'])").click()
            page.screenshot(path=f"{SHOTS}/03b_sidebar.png")

            # redoing ONE character must not touch scenes or props
            def stats():
                return __import__("json").loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/mock/stats").read())
            before = stats()
            check("step 2 drew 6 scene images, 2 props, 6 character versions",
                  (before["scene"], before["prop"], before["cast"]) == (6, 2, 6), str(before))
            first_cast_src = page.get_attribute(".card[data-step='2'] input[data-sel=cast][data-id='1'][data-val='1'] ~ img", "src")
            page.click("button[data-act=redo-cast][data-char='1']")
            page.wait_for_selector("#dock:not(.hidden)")
            wait_idle(page)
            after = stats()
            check("redo character: only characters redrawn (scenes/props untouched)",
                  after["scene"] == before["scene"] and after["prop"] == before["prop"] and after["cast"] == before["cast"] + 3,
                  f"{before} -> {after}")
            check("redo character: message says so", "角色已重画" in page.inner_text("#dockMsg"), page.inner_text("#dockMsg"))
            new_cast_src = page.get_attribute(".card[data-step='2'] input[data-sel=cast][data-id='1'][data-val='1'] ~ img", "src")
            check("redo character: new image shown", new_cast_src.split("&t=")[0] != first_cast_src.split("&t=")[0])
            check("scenes + props still displayed after cast-only redo",
                  page.locator(".card[data-step='2'] input[data-sel=scene]").count() == 6 and
                  page.locator(".card[data-step='2'] .group:last-child img").count() >= 1)
            check("picks survived the redo", page.evaluate("() => S.settings.scene_view_picks") == "1:2")
            page.click("button[data-act=run][data-stage='2']")
            page.wait_for_selector("#dock:not(.hidden)")
            wait_idle(page)
            again = stats()
            check("re-running step 2 reuses scene/props images from disk",
                  again["scene"] == before["scene"] and again["prop"] == before["prop"], str(again))

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
            check("changing a pick marks step 3 as needing update",
                  page.locator("#side .stale").count() == 1 and page.locator("#stepper .step-chip.stale").count() == 1)
            page.screenshot(path=f"{SHOTS}/04b_stale.png")
            page.click("#side .stale button")
            wait_idle(page)
            page.wait_for_selector("#side .fresh")
            check("updating from the sidebar clears the warning",
                  page.locator("#side .stale").count() == 0 and page.locator("#stepper .step-chip.stale").count() == 0)

            # step 4
            page.click("button[data-act=run][data-stage='4']")
            wait_idle(page, 90000)
            page.wait_for_selector(".card[data-step='4'] video")
            check("2 clips rendered", page.locator(".card[data-step='4'] video").count() == 2)
            page.fill(".card[data-step='4'] input[data-long='shot_001']", "10")
            page.dispatch_event(".card[data-step='4'] input[data-long='shot_001']", "change")
            check("long take stored", page.evaluate("() => S.settings.long_takes") == "shot_001:10")
            page.locator(".card[data-step='4'] input[data-skip='shot_002']").click()
            page.evaluate("() => { ['shot_003','shot_004','shot_005','shot_006'].forEach(x => S.skip.add(x)); syncToSettings(); render(); }")
            check("skip stored", page.evaluate("() => S.settings.skip_shots") == "shot_002, shot_003, shot_004, shot_005, shot_006")
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
            check("after reload: script restored", "小红看电视" in page.input_value("textarea[data-set=script]"))

            # upstream change makes downstream stale: redraw a first frame after video + movie exist
            page.evaluate("() => { S.open[3] = true; render(); }")
            page.click("button[data-act=redo-kf][data-shot='shot_002']")
            page.wait_for_selector("#dock:not(.hidden)"); wait_idle(page)
            check("redrawing a first frame marks the video step stale",
                  page.locator("#stepper .step-chip.stale").count() == 1 and "视频" in page.inner_text("#stepper .step-chip.stale"),
                  page.inner_text("#stepper"))
            page.click("#side .stale button")                    # updates video (only shot_002 changed)
            wait_idle(page, 90000)
            check("after updating video the movie is the stale step",
                  page.locator("#stepper .step-chip.stale").count() == 1 and "成片" in page.inner_text("#stepper .step-chip.stale"))
            page.click("#side .stale button")
            wait_idle(page, 60000)
            check("everything fresh again", page.locator("#side .stale").count() == 0 and page.locator("#side .fresh").count() == 1)

            # ---- the user's own reference pictures ----
            from PIL import Image
            png = os.path.join(tempfile.gettempdir(), "afe_ref.png")
            Image.new("RGB", (300, 500), (200, 30, 30)).save(png)
            page.evaluate("() => { S.open[2] = true; render(); }")
            check("reference section is open by default once the script is analysed",
                  page.evaluate("() => document.querySelector('.card[data-step=\"2\"] details.refs').open"))
            page.evaluate("() => { document.querySelector('details.props').open = true; }")
            before = stats()
            for n, (kind, name) in enumerate([("cast", "阿明"), ("scene", "超市外卖厨房"), ("prop", "佛珠")], start=1):
                page.set_input_files(f"input[data-ref-kind={kind}][data-ref-name='{name}']", png)
                page.wait_for_function(f"() => document.querySelectorAll('.refrow .thumb img').length >= {n}")
            check("3 uploads show thumbnails", page.locator(".refrow .thumb img").count() == 3)
            page.locator(".card[data-step='2']").screenshot(path=f"{SHOTS}/07_refs.png")
            check("uploading marks steps stale and says why",
                  "参考图" in page.inner_text("#side .stale") and page.locator("#stepper .step-chip.stale").count() >= 1,
                  page.inner_text("#side .stale")[:60])
            page.click("#side .stale button")                      # first stale step = 2 (materials)
            wait_idle(page, 90000)
            after = stats()
            check("only the pictures that depend on uploads were redrawn (5 Qwen edits, no new text-to-image)",
                  after["qwen"] == before["qwen"] + 5 and after["scene"] == before["scene"]
                  and after["prop"] == before["prop"] and after["cast"] == before["cast"], f"{before} -> {after}")
            page.wait_for_selector(".card[data-step='2'] .group")
            ming = page.inner_text(".card[data-step='2'] .group:has(h3:has-text('阿明'))")
            check("character candidates: v1 is labelled as the user's own picture", "你的原图" in ming, ming[:40])
            check("sidebar says 'your picture' for that character", "你的原图" in page.inner_text("#side"))
            kf_before = len(stats()["kf_imgs"])
            for _ in range(4):                                     # step 3 (first frames), then 4, 5 ...
                if page.locator("#side .stale").count() == 0:
                    break
                page.click("#side .stale button")
                wait_idle(page, 90000)
            counts = stats()["kf_imgs"][kf_before:]
            check("first frames now receive every selected prop picture too (scene + characters + all props)",
                  set(counts) == {3, 5}, str(counts))
            check("everything fresh after propagating the uploads", page.locator("#side .stale").count() == 0)
            page.click("button[data-act=ref-del][data-kind=prop]")
            page.wait_for_function("() => document.querySelectorAll('.refrow .thumb img').length === 2")
            check("removing a reference picture works and flags an update", page.locator("#side .stale").count() == 1)

            # a job that vanishes (ComfyUI restarted) must not leave the page waiting forever
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/mock/lose_next").read()
            page.evaluate("() => { S.open[2] = true; render(); }")
            page.click(".card[data-step='2'] button[data-act=run][data-stage='2']")
            page.wait_for_selector("#dock.err", timeout=40000)
            check("lost job is detected, with a clear message", "被中断" in page.inner_text("#dockMsg"), page.inner_text("#dockMsg"))
            check("buttons usable again after a lost job",
                  page.locator(".card[data-step='2'] button[data-act=run][data-stage='2']").is_enabled())
            page.click("#dockClose")

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
