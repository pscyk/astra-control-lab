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
            page.wait_for_function("document.querySelectorAll('.case-buttons button').length === 5")
            assert page.locator("#rescues").inner_text() == "53"
            assert page.locator("#regressions").inner_text() == "4"
            assert page.locator(".score").count() == 3
            assert page.locator("#teacher-score").inner_text() == "15/15"
            assert page.locator("#loop-score").inner_text() == "2/3"
            assert page.locator("#loop-base-score").inner_text() == "1/3"
            assert page.locator("#known-loop-score").inner_text() == "0/3"
            assert page.locator("video").count() == 4
            for index in range(5):
                page.locator(".case-buttons button").nth(index).click()
                page.wait_for_function("!document.querySelector('#play').disabled")
                case_id = page.locator(".case-buttons button").nth(index).get_attribute("data-case")
                assert f"view={case_id}" in page.url
                assert page.locator("#case-link").get_attribute("href").endswith(f"view={case_id}#replay")
                assert page.locator("video").count() == (4 if index == 0 else 2)
                assert page.locator("#comparison-scope").is_visible() == (index in [0, 4])
                assert "undefined" not in page.locator("#case-meta").inner_text()
                assert "[object Object]" not in page.locator(".players").inner_text()
                assert len(page.locator(".video-detail").first.inner_text()) < 120
                if index == 0 and width == 1440:
                    boxes = [figure.bounding_box() for figure in page.locator(".players figure").all()]
                    assert len({box["y"] for box in boxes}) == 1
                    assert all(left["x"] < right["x"] for left, right in zip(boxes, boxes[1:]))
                page.locator("#play").click()
                page.wait_for_timeout(800)
                assert page.locator("#play").inner_text() == ("Pause all four" if index == 0 else "Pause both")
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
            assert page.locator("video").nth(1).evaluate("video => Math.abs(video.currentTime - Number(video.dataset.playbackEnd)) < 0.01")
            for index in [1, 3]:
                assert page.locator("video").nth(index).evaluate("""video => {
                    const canvas = document.createElement('canvas');
                    canvas.width = canvas.height = 1;
                    const context = canvas.getContext('2d');
                    context.drawImage(video, 0, 0, 1, 1);
                    const pixel = context.getImageData(0, 0, 1, 1).data;
                    return !(pixel[0] < 10 && pixel[1] > 245 && pixel[2] < 10);
                }""")
            page.locator("#play").click()
            page.wait_for_timeout(300)
            assert page.locator("video").nth(1).evaluate("video => video.paused")
            assert page.locator("video").first.evaluate("video => video.currentTime > 8")
            page.locator("#play").click()
            page.locator("video").evaluate_all("videos => videos.forEach(video => video.controls = false)")
            page.wait_for_timeout(500)
            page.screenshot(path=str(args.output / f"page-{width}.png"), full_page=True)
            if width == 1440:
                page.locator("#replay").screenshot(path=str(args.output / "preview.png"))
            for view, expected in [("drawer", "drawer"), ("invalid", "overview")]:
                page.goto(f"{args.url.rstrip('/')}/?view={view}#replay")
                page.wait_for_function("!document.querySelector('#play').disabled")
                assert page.locator(".case-buttons button[aria-pressed=true]").get_attribute("data-case") == expected
                page.reload()
                page.wait_for_function("!document.querySelector('#play').disabled")
                assert page.locator(".case-buttons button[aria-pressed=true]").get_attribute("data-case") == expected
            checks.append({"width": width, "deep_links_reload_invalid_view": "pass", "shorter_clip_hold": "pass"})
            page.close()
        browser.close()
    assert not errors, errors
    result = {"checks": checks, "browser_errors": errors, "new_model_calls": 0, "new_simulator_rollouts": 0}
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
