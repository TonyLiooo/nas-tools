import time
import os

from pyquery import PyQuery

from nodriver import Tab
import asyncio
import log


ACCESS_DENIED_TITLES = [
    # Cloudflare
    'Access denied',
    # Cloudflare http://bitturk.net/ Firefox
    'Attention Required! | Cloudflare'
]

ACCESS_DENIED_SELECTORS = [
    # Cloudflare
    'div.cf-error-title span.cf-code-label span',
    # Cloudflare http://bitturk.net/ Firefox
    '#cf-error-details div.cf-error-overview h1'
]

CHALLENGE_TITLES = [
    # Cloudflare
    'Just a moment...',
    '请稍候…',
    # DDoS-GUARD
    'DDoS-Guard'
]

CHALLENGE_SELECTORS_STRICT = [
    # Cloudflare challenge-only selectors
    '#cf-challenge-running', '.ray_id', '.attack-box', '#cf-please-wait', '#challenge-spinner',
    '#trk_jschal_js', '.lds-ring',
    # Custom CloudFlare for EbookParadijs, Film-Paleis, MuziekFabriek and Puur-Hollands
    'td.info #js_info',
    # Fairlane / pararius.com
    'div.vc div.text-box h2',
    # chaitin
    'button#sl-check',
    # Slider verification
    '#dragContainer', '#dragHandler', '.dragHandlerBg'
]

EMBEDDED_CAPTCHA_SELECTORS = [
    '#turnstile-wrapper', 'div.g-recaptcha', 'div.h-captcha',
    '.cf-turnstile',
]

CHALLENGE_SELECTORS = CHALLENGE_SELECTORS_STRICT + EMBEDDED_CAPTCHA_SELECTORS
SHORT_TIMEOUT = 10
CF_TIMEOUT = int(os.getenv("NASTOOL_CF_TIMEOUT", "120"))


async def resolve_challenge(tab: Tab, timeout=CF_TIMEOUT):
    start_ts = time.time()
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            await asyncio.wait_for(_evil_logic(tab), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            if attempt < max_retries:
                await tab.reload()
                await asyncio.sleep(1)
                continue
            log.error(f'Error solving the challenge. Timeout {timeout} after {round(time.time() - start_ts, 1)} seconds.')
            return False
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(1)
                continue
            log.error('Error solving the challenge. ' + str(e))
            return False


def under_challenge(html_text: str):
    """
    Check if the page is under challenge
    :param html_text:
    :return:
    """
    if not html_text:
        return False
    page_title = PyQuery(html_text)('title').text()
    log.debug("under_challenge page_title=" + page_title)
    for title in CHALLENGE_TITLES:
        if page_title.lower() == title.lower():
            return True
    for selector in CHALLENGE_SELECTORS_STRICT:
        html_doc = PyQuery(html_text)
        if html_doc(selector):
            return True
    return False

async def check_document_ready(tab:Tab):
    while await tab.evaluate('document.readyState') == 'loading':
        try:
            title = (tab.target.title or '').lower()
            if any(title == t.lower() for t in CHALLENGE_TITLES):
                log.debug(f"CF challenge detected (title='{title}'), skipping document ready wait")
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return True

async def _until_match_func(tab: Tab, item, match_func, async_type=True):
    if async_type:
        while not await match_func(tab, item):
            await asyncio.sleep(0.1)
    else:
        while not match_func(tab, item):
            await asyncio.sleep(0.1)
    return True
            
async def _wait_until_condition(tab: Tab, items, match_func, async_type=True, timeout=SHORT_TIMEOUT, message=''):
    for item in items:
        try:
            start_ts = time.time()
            await asyncio.wait_for(_until_match_func(tab, item, match_func, async_type), timeout=timeout)
            log.debug(f"Waiting for condition: {item} in {round(time.time() - start_ts, 1)} seconds")
        except asyncio.TimeoutError:
            log.debug(f"Timeout waiting for condition: {item}, {message}")
            return False
        except Exception as e:
            log.error(f"Error while waiting for condition: {item}, Error: {e}")
            return False
    return True
    
async def _any_match(tab: Tab, items, match_func, async_type=True):
    for item in items:
        if async_type:
            if await match_func(tab, item):
                return item
        else:
            if match_func(tab, item):
                return item
    return None

async def async_match_selectors(p:Tab, s):
        return await p.query_selector(s) is not None

async def async_match_selectors_not(p: Tab, s):
    return await p.query_selector(s) is None

async def _any_match_titles(tab: Tab, titles):
    return await _any_match(tab, titles, lambda d, t: d.target.title.lower() == t.lower(), async_type=False)

async def _any_match_selectors(tab: Tab, selectors):
    return await _any_match(tab, selectors, async_match_selectors, async_type=True)


async def _evil_logic(tab: Tab):
    # wait for the page to load
    try:
        await asyncio.wait_for(check_document_ready(tab), 20)
    except asyncio.TimeoutError:
        log.debug("Timeout waiting for the page")

    # find access denied titles and selectors
    if await _any_match_titles(tab, ACCESS_DENIED_TITLES) or await _any_match_selectors(tab, ACCESS_DENIED_SELECTORS):
        raise Exception('Cloudflare has blocked this request. Probably your IP is banned for this site, check in your web browser.')

    title_challenge = await _any_match_titles(tab, CHALLENGE_TITLES)
    strict_selector_challenge = await _any_match_selectors(tab, CHALLENGE_SELECTORS_STRICT)

    challenge_found = title_challenge or strict_selector_challenge

    if challenge_found:
        # Determine which selectors to wait for: on a real challenge page we
        # wait for ALL selectors (including embedded CAPTCHAs) to disappear;
        # otherwise only strict challenge selectors need to clear.
        wait_selectors = CHALLENGE_SELECTORS if title_challenge else CHALLENGE_SELECTORS_STRICT

        while not (await _wait_until_condition(tab, CHALLENGE_TITLES, lambda d, t: d.target.title.lower() != t.lower(), async_type=False, message="title changes") and
                   await _wait_until_condition(tab, wait_selectors, async_match_selectors_not, async_type=True, message="selectors disappear")):
            log.debug("Timeout waiting for selector")
            verification_result = await click_verify(tab)
            if verification_result:
                log.info("Human verification completed successfully!")
                break

        log.info("Challenge solved!")
    else:
        log.info("Challenge not detected!")


async def drag_slider_verify(tab: Tab):
    """
    Handle slider verification with multiple slider types
    """
    # target the specified DOM structure directly
    try:
        # wait up to SHORT_TIMEOUT for the slider to appear
        start_ts = time.time()
        drag_container = None
        drag_handler = None
        while time.time() - start_ts < SHORT_TIMEOUT:
            drag_container = await tab.query_selector('#dragContainer')
            drag_handler = await tab.query_selector('#dragHandler')
            if drag_container and drag_handler:
                break
            await asyncio.sleep(0.1)
        if not drag_container or not drag_handler:
            return False
        await drag_handler.scroll_into_view()
        # compute target drag distance
        container_box = await drag_container.get_position()
        handler_box = await drag_handler.get_position()
        if not container_box or not handler_box:
            return False
        drag_distance = max(0, (container_box.width or 0) - (handler_box.width or 0) - 3)
        if drag_distance <= 0:
            return False
        log.debug(f"Dragging slider {drag_distance}px")
        # perform a smooth drag
        await drag_handler.mouse_drag(
            destination=(drag_distance, 0),
            relative=True,
            steps=40
        )
        success_deadline = time.time() + 15
        while time.time() < success_deadline:
            try:
                passed = await tab.evaluate(
                    """() => {
                        const h = document.querySelector('#dragHandler');
                        const c = document.querySelector('#dragContainer');
                        if (!h) return true;
                        if (!c) return true;
                        const hs = window.getComputedStyle(h);
                        const cs = window.getComputedStyle(c);
                        const hRect = h.getBoundingClientRect();
                        const cRect = c.getBoundingClientRect();
                        const hHidden = hs.display === 'none' || hs.visibility === 'hidden' || parseFloat(hs.opacity) === 0 || h.offsetParent === null || (hRect.width === 0 && hRect.height === 0);
                        const cHidden = cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0 || c.offsetParent === null || (cRect.width === 0 && cRect.height === 0);
                        return hHidden || cHidden;
                    }"""
                )
                if passed:
                    log.debug("Slider passed by hidden/removed state")
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
        return False
    except Exception as e:
        log.debug(f"Slider verify error: {str(e)}")
        return False


async def check_verification_success(tab: Tab, success_selectors=None, timeout=10):
    """
    检查人机验证是否成功完成
    :param tab: Tab对象
    :param success_selectors: 要检查的成功标志选择器列表，为None时使用默认值
    :param timeout: 等待超时时间
    :return: True表示验证成功，False表示验证失败或超时
    """
    from app.helper import ChromeHelper
    
    if success_selectors is None:
        success_selectors = [
            'div[role="alert"] #success-text',
            'span[id="success-text"]',
        ]
    
    challenge_selectors = [
        'div[class*="main-wrapper"] input[type=checkbox]',  # Cloudflare主要验证框
        '.cf-turnstile',                                     # Turnstile验证
        '#turnstile-wrapper',                                # Turnstile包装器
    ]
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            success_found = False
            for selector in success_selectors:
                found, coordinates = await ChromeHelper.find_element(tab, selector)
                if found:
                    log.debug(f"Found success element: {selector} at {coordinates}")
                    success_found = True
                    break
            
            challenge_gone = True
            for selector in challenge_selectors:
                found, _ = await ChromeHelper.find_element(tab, selector)
                if found:
                    log.debug(f"Challenge element still present: {selector}")
                    challenge_gone = False
                    break
            
            if success_found:
                log.debug("Verification success: success element found")
                return True
            if challenge_gone:
                log.debug("Challenge elements gone")
                return True
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            log.debug(f"Error checking verification success: {str(e)}")
            await asyncio.sleep(0.5)
    
    log.debug("Verification success check timeout")
    return False

async def click_verify(tab: Tab):
    from app.helper import ChromeHelper

    # Try Cloudflare checkbox verification
    try:
        log.debug("Try to find the Cloudflare verify checkbox")
        selector = "div[class*='main-wrapper'] input[type=checkbox]"
        status, coordinates = await ChromeHelper.find_and_click_element(tab=tab, selector=selector)
        if status:
            log.debug(f"Cloudflare verify checkbox found and clicked at {coordinates}")
            if await check_verification_success(tab, success_selectors=None):
                try:
                    await asyncio.wait_for(check_document_ready(tab), 20)
                except asyncio.TimeoutError:
                    log.debug("Timeout waiting for the page")
                return True
        else:
            log.debug("Cloudflare verify checkbox not found")
    except Exception as e:
        log.debug(f"Cloudflare verify checkbox not found: {str(e)}")

    # Try chaitin verification button
    try:
        log.debug("Try to find the chaitin verify checkbox")
        selector = "button[@id='sl-check']"
        status, coordinates = await ChromeHelper.find_and_click_element(tab=tab, selector=selector)
        if status:
            log.debug(f"chaitin verify checkbox found and clicked at {coordinates}")
            try:
                await asyncio.wait_for(check_document_ready(tab), 20)
            except asyncio.TimeoutError:
                log.debug("Timeout waiting for the page")
        else:
            log.debug("chaitin verify checkbox not found")
    except Exception as e:
        log.debug(f"chaitin verify checkbox not found: {str(e)}")
        
    # Try slider verification first
    try:
        if await drag_slider_verify(tab):
            log.debug("Slider verification completed successfully")
            try:
                await asyncio.wait_for(check_document_ready(tab), 20)
            except asyncio.TimeoutError:
                log.debug("Timeout waiting for the page")
            return True
    except Exception as e:
        log.debug(f"Slider verification error: {str(e)}")
    
    try:
        await asyncio.wait_for(check_document_ready(tab), 20)
    except asyncio.TimeoutError:
        log.debug("Timeout waiting for the page")
    
    return False
