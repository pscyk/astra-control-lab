import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description="Optional browser test. Requires Playwright and Chromium.")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--chromium")
    parser.add_argument("--output", type=Path, default=Path("/tmp/astra-browser-qa"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    errors = []
    checks = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=args.chromium, headless=True)
        for width, height in [(1440, 1000), (390, 844)]:
            page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.url)
            page.wait_for_function("document.querySelectorAll('.case-buttons button').length === 4")
            assert page.locator("#rescues").inner_text() == "53"
            assert page.locator("#regressions").inner_text() == "4"
            assert page.locator(".score").count() == 3
            for index in range(4):
                page.locator(".case-buttons button").nth(index).click()
                page.wait_for_function("!document.querySelector('#play').disabled")
                assert "[object Object]" not in page.locator(".players").inner_text()
                assert len(page.locator(".video-detail").first.inner_text()) < 120
                page.locator("#play").click()
                page.wait_for_timeout(800)
                assert page.locator("#play").inner_text() == "Pause both"
                assert all(value > 0 for value in page.locator("video").evaluate_all("videos => videos.map(video => video.currentTime)"))
                page.locator("#play").click()
                assert all(page.locator("video").evaluate_all("videos => videos.map(video => video.paused)"))
                page.locator("#timeline").evaluate("slider => { slider.value = Math.min(2, slider.max); slider.dispatchEvent(new Event('input')); }")
                page.wait_for_timeout(200)
                assert page.locator("#clock").inner_text() == "2.0 s"
                page.locator("#reset").click()
                assert page.locator("#clock").inner_text() == "0.0 s"
                checks.append({"width": width, "case": index, "play_pause_seek_reset": "pass"})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not page.locator("#load-status").inner_text()
            page.locator(".case-buttons button").first.click()
            page.wait_for_function("!document.querySelector('#play').disabled")
            page.locator("#timeline").evaluate("slider => { slider.value = 8; slider.dispatchEvent(new Event('input')); }")
            page.wait_for_function("Array.from(document.querySelectorAll('video')).every(video => !video.seeking)")
            page.locator("video").evaluate_all("videos => videos.forEach(video => video.controls = false)")
            page.wait_for_timeout(500)
            page.screenshot(path=str(args.output / f"page-{width}.png"), full_page=True)
            if width == 1440:
                page.locator("#replay").screenshot(path=str(args.output / "preview.png"))
            page.close()
        browser.close()
    assert not errors, errors
    result = {"checks": checks, "browser_errors": errors, "new_model_calls": 0, "new_simulator_rollouts": 0}
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
