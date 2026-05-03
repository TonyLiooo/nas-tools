import time
import os
import re
import json
from random import randint, uniform

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

# --- Scrapling-inspired challenge type detection ---
_CF_CTYPE_PATTERN = re.compile(r"cType:\s*'(non-interactive|managed|interactive)'")
_CF_TURNSTILE_SCRIPT_PATTERN = re.compile(r'challenges\.cloudflare\.com/turnstile/v')


def detect_challenge_type(html_content: str):
    """
    检测 Cloudflare 挑战类型，参考 Scrapling _detect_cloudflare 方法。
    
    通过页面 HTML 源码中的 cType 标识精确判定挑战机制：
    - 'non-interactive': 无需任何操作，只需等待自动通过
    - 'managed': 托管式挑战，可能需要点击
    - 'interactive': 交互式挑战，需要点击验证
    - 'embedded': 嵌入式 Turnstile 验证码
    - None: 无挑战或无法识别
    
    :param html_content: 页面 HTML 内容
    :return: 挑战类型字符串或 None
    """
    if not html_content:
        return None
    
    match = _CF_CTYPE_PATTERN.search(html_content)
    if match:
        return match.group(1)
    
    # 检查是否为嵌入式 Turnstile（通常在 Shadow iframe 内）
    if _CF_TURNSTILE_SCRIPT_PATTERN.search(html_content):
        return "embedded"
    
    return None


async def resolve_challenge(tab: Tab, timeout=CF_TIMEOUT):
    start_ts = time.time()
    challenge_type = None
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            result, challenge_type = await asyncio.wait_for(_evil_logic(tab), timeout=timeout)
            elapsed_ms = round((time.time() - start_ts) * 1000)
            if result:
                if challenge_type:
                    log.info(f"[CF] 挑战通过，类型={challenge_type}，耗时={elapsed_ms}ms")
                else:
                    log.debug(f"[CF] 无挑战，页面正常，耗时={elapsed_ms}ms")
            else:
                log.warn(f"[CF] 挑战未通过，类型={challenge_type or 'unknown'}，耗时={elapsed_ms}ms")
            return bool(result)
        except asyncio.TimeoutError:
            if attempt < max_retries:
                await tab.reload()
                await asyncio.sleep(1)
                continue
            elapsed_ms = round((time.time() - start_ts) * 1000)
            log.error(f'[CF] 挑战超时，类型={challenge_type or "unknown"}，超时={timeout}s，耗时={elapsed_ms}ms')
            return False
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(1)
                continue
            elapsed_ms = round((time.time() - start_ts) * 1000)
            log.error(f'[CF] 挑战异常，类型={challenge_type or "unknown"}，耗时={elapsed_ms}ms，错误: {e}')
            return False


def under_challenge(html_text: str, include_embedded: bool = False):
    """
    Check if the page is under challenge
    :param html_text:
    :param include_embedded: 是否将嵌入式验证码组件视为challenge
    :return:
    """
    if not html_text:
        return False
    page_title = PyQuery(html_text)('title').text()
    log.debug("under_challenge page_title=" + page_title)
    for title in CHALLENGE_TITLES:
        if page_title.lower() == title.lower():
            return True
    selectors = CHALLENGE_SELECTORS_STRICT + EMBEDDED_CAPTCHA_SELECTORS if include_embedded else CHALLENGE_SELECTORS_STRICT
    html_doc = PyQuery(html_text)
    for selector in selectors:
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


async def wait_for_page_stability(tab: Tab, timeout=15):
    """
    等待页面稳定：DOM 加载完成 + 网络空闲。
    参考 Scrapling 的 _wait_for_page_stability：load -> domcontentloaded -> networkidle。
    
    :param tab: Tab对象
    :param timeout: 超时时间（秒）
    """
    start = time.time()
    
    # Phase 1: 等待 readyState == 'complete'
    while time.time() - start < timeout:
        try:
            state = await tab.evaluate('document.readyState')
            if state == 'complete':
                break
        except Exception:
            pass
        await asyncio.sleep(0.3)
    
    # Phase 2: 网络空闲检测（检查是否有未完成的资源加载）
    idle_start = time.time()
    while time.time() - start < timeout:
        try:
            pending = await tab.evaluate("""
                (() => {
                    try {
                        const entries = performance.getEntriesByType('resource');
                        let pending = 0;
                        for (let i = entries.length - 1; i >= Math.max(0, entries.length - 20); i--) {
                            if (entries[i].responseEnd === 0) pending++;
                        }
                        return pending;
                    } catch(e) { return 0; }
                })()
            """)
            if pending == 0 or pending is None:
                # 连续 0.5s 无活动认为网络空闲
                if time.time() - idle_start > 0.5:
                    break
            else:
                idle_start = time.time()
        except Exception:
            break
        await asyncio.sleep(0.2)


async def _is_challenge_title_present(tab: Tab):
    """检查当前 tab title 是否为 CF 挑战 title"""
    try:
        title = (tab.target.title or '').lower()
        return any(title == t.lower() for t in CHALLENGE_TITLES)
    except Exception:
        return False


async def _wait_for_challenge_title_gone(tab: Tab, timeout=60):
    """
    等待 CF 挑战 title 消失（用于 non-interactive 模式）。
    不执行任何 DOM 查询或点击，只检查 title。
    """
    start = time.time()
    while time.time() - start < timeout:
        if not await _is_challenge_title_present(tab):
            return True
        await asyncio.sleep(1)
    return False


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
    """
    核心挑战处理逻辑。
    返回 (result: bool, challenge_type: str|None)
    """
    challenge_type = None
    
    # wait for the page to load
    try:
        await asyncio.wait_for(check_document_ready(tab), 20)
    except asyncio.TimeoutError:
        log.debug("Timeout waiting for the page")

    # find access denied titles and selectors
    if await _any_match_titles(tab, ACCESS_DENIED_TITLES) or await _any_match_selectors(tab, ACCESS_DENIED_SELECTORS):
        raise Exception('Cloudflare has blocked this request. Probably your IP is banned for this site, check in your web browser.')

    # --- Phase 1: 检测挑战类型 ---
    try:
        html_content = await tab.get_content()
        challenge_type = detect_challenge_type(html_content)
        if challenge_type:
            log.info(f"[CF] 识别挑战类型: {challenge_type}")
    except Exception as e:
        log.debug(f"[CF] 获取页面内容检测挑战类型失败: {e}")

    title_challenge = await _any_match_titles(tab, CHALLENGE_TITLES)
    strict_selector_challenge = await _any_match_selectors(tab, CHALLENGE_SELECTORS_STRICT)

    challenge_found = title_challenge or strict_selector_challenge

    if challenge_found:
        # --- Phase 2: 按挑战类型分类施治 ---
        
        if challenge_type == 'non-interactive':
            # non-interactive 模式：只需静默等待，不做任何点击或 DOM 查询
            # 参考 Scrapling: 只循环等待 "Just a moment..." title 消失
            log.info("[CF] non-interactive 类型，静默等待自动通过...")
            if await _wait_for_challenge_title_gone(tab, timeout=60):
                await wait_for_page_stability(tab, timeout=10)
                log.info("[CF] non-interactive 挑战已自动通过")
                return True, challenge_type
            else:
                log.warn("[CF] non-interactive 等待超时，尝试常规验证流程")
                # 降级到常规处理
        
        # managed / interactive / unknown 模式：使用验证点击
        wait_selectors = CHALLENGE_SELECTORS if title_challenge else CHALLENGE_SELECTORS_STRICT

        async def _challenge_cleared():
            return (await _wait_until_condition(tab, CHALLENGE_TITLES, lambda d, t: d.target.title.lower() != t.lower(),
                                                async_type=False, message="title changes") and
                    await _wait_until_condition(tab, wait_selectors, async_match_selectors_not,
                                                async_type=True, message="selectors disappear"))

        # 对于 managed 类型，先等待 "Verifying you are human." 消失
        if challenge_type == 'managed':
            log.info("[CF] managed 类型，等待验证旋转器消失...")
            verify_start = time.time()
            while time.time() - verify_start < 10:
                try:
                    content = await tab.get_content()
                    if "Verifying you are human." not in content:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)

        solved = await _challenge_cleared()
        while not solved:
            log.debug("[CF] 挑战未清除，尝试验证点击")
            verification_result = await click_verify(tab)
            if verification_result:
                log.info("[CF] 人机验证点击完成")
            solved = await _challenge_cleared()

        if solved:
            await wait_for_page_stability(tab, timeout=10)
            return True, challenge_type
        return False, challenge_type
    else:
        embedded_captcha = await _any_match_selectors(tab, EMBEDDED_CAPTCHA_SELECTORS)
        if embedded_captcha:
            challenge_type = challenge_type or "embedded"
            log.info(f"[CF] 嵌入式验证码检测到: {embedded_captcha}，类型={challenge_type}")
            await asyncio.sleep(2)
            if await check_verification_success(tab, success_selectors=None, timeout=SHORT_TIMEOUT):
                log.info("[CF] 嵌入式验证码已自动通过")
                return True, challenge_type
            if await click_verify(tab):
                await wait_for_page_stability(tab, timeout=10)
                return True, challenge_type
            if await check_verification_success(tab, success_selectors=None, timeout=SHORT_TIMEOUT):
                log.info("[CF] 嵌入式验证码在点击后自动通过")
                return True, challenge_type
            log.info("[CF] 嵌入式验证码无法自动解决")
            return False, challenge_type
        else:
            return True, challenge_type


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
    
    success_selectors = success_selectors or []
    
    challenge_selectors = [
        'div[class*="main-wrapper"] input[type=checkbox]',  # Cloudflare主要验证框
        '.cf-turnstile',                                     # Turnstile验证
        '#turnstile-wrapper',                                # Turnstile包装器
    ]
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            token_valid = await tab.evaluate("""
                (() => {
                    const t = document.querySelector('[name="cf-turnstile-response"]');
                    return !!(t && t.value && t.value.length > 10);
                })()
            """)
            if token_valid:
                log.debug("Verification success: valid turnstile token found")
                return True
            
            challenge_gone = True
            for selector in challenge_selectors:
                found, _ = await ChromeHelper.find_element(tab, selector)
                if found:
                    log.debug(f"Challenge element still present: {selector}")
                    challenge_gone = False
                    break

            success_found = False
            for selector in success_selectors:
                found, coordinates = await ChromeHelper.find_element(tab, selector)
                if found:
                    log.debug(f"Found success element: {selector} at {coordinates}")
                    success_found = True
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

async def click_turnstile(tab: Tab, timeout=15, max_attempts=3):
    """
    通过viewport坐标点击Turnstile checkbox。
    使用随机坐标偏移和点击延迟，模拟真实人类操作。
    """
    from app.helper import ChromeHelper

    for attempt in range(1, max_attempts + 1):
        try:
            pre_check = await tab.evaluate("""
                (() => {
                    const t = document.querySelector('[name="cf-turnstile-response"]');
                    return (t && t.value && t.value.length > 10) ? 'true' : 'false';
                })()
            """)
            if pre_check == 'true':
                log.info("click_turnstile: Turnstile already has valid token")
                return True

            pos_json = await tab.evaluate("""
                (() => {
                    const cf = document.querySelector('.cf-turnstile');
                    if (!cf) return 'null';
                    const rect = cf.getBoundingClientRect();
                    return JSON.stringify({x: rect.x, y: rect.y, w: rect.width, h: rect.height});
                })()
            """)

            if not pos_json or pos_json == 'null':
                log.debug("click_turnstile: .cf-turnstile element not found")
                return False

            pos = json.loads(pos_json)
            if not pos.get('w') or pos['w'] <= 0:
                log.debug(f"click_turnstile: invalid element dimensions: {pos}")
                return False

            # checkbox 固定在 widget 左侧约 26-28px 处，垂直 25-27px
            cx = pos['x'] + randint(26, 28)
            cy = pos['y'] + randint(25, 27)

            log.debug(f"click_turnstile: attempt {attempt}/{max_attempts}, "
                       f"Turnstile rect=({pos['x']:.1f}, {pos['y']:.1f}, {pos['w']:.0f}x{pos['h']:.0f}), "
                       f"clicking checkbox at ({cx:.1f}, {cy:.1f})")

            await asyncio.sleep(uniform(0.02, 0.08))

            await tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                'type': 'mouseMoved', 'x': cx, 'y': cy, 'button': 'none'
            }), _is_update=True)
            
            await asyncio.sleep(uniform(0.05, 0.15))

            await tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                'type': 'mousePressed', 'x': cx, 'y': cy, 'button': 'left', 'clickCount': 1
            }), _is_update=True)
            
            # 按下和释放之间的随机延迟（模拟人类按下时长）
            # 参考 Scrapling: delay=randint(100, 200) ms
            await asyncio.sleep(uniform(0.10, 0.20))

            await tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                'type': 'mouseReleased', 'x': cx, 'y': cy, 'button': 'left', 'clickCount': 1
            }), _is_update=True)

            log.debug("click_turnstile: click dispatched, waiting for token...")

            start = time.time()
            while time.time() - start < timeout:
                token_check = await tab.evaluate("""
                    (() => {
                        const t = document.querySelector('[name="cf-turnstile-response"]');
                        return (t && t.value && t.value.length > 10) ? 'true' : 'false';
                    })()
                """)
                if token_check == 'true':
                    log.info(f"click_turnstile: Turnstile verification successful! (attempt {attempt})")
                    return True
                await asyncio.sleep(0.5)

            log.debug(f"click_turnstile: attempt {attempt} timeout, token not obtained")

        except Exception as e:
            log.error(f"click_turnstile: attempt {attempt} error: {e}")

        if attempt < max_attempts:
            await asyncio.sleep(1)

    log.debug(f"click_turnstile: all {max_attempts} attempts failed")
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
            await asyncio.sleep(uniform(0.05, 0.15))
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

    # Try Turnstile embedded captcha (uses dispatchMouseEvent on .cf-turnstile position)
    try:
        log.debug("Try to click Turnstile embedded captcha")
        if await click_turnstile(tab):
            log.debug("Turnstile verification completed successfully")
            try:
                await asyncio.wait_for(check_document_ready(tab), 20)
            except asyncio.TimeoutError:
                log.debug("Timeout waiting for the page")
            return True
    except Exception as e:
        log.debug(f"Turnstile click error: {str(e)}")

    # Try chaitin verification button
    try:
        log.debug("Try to find the chaitin verify checkbox")
        selector = "button[@id='sl-check']"
        status, coordinates = await ChromeHelper.find_and_click_element(tab=tab, selector=selector)
        if status:
            log.debug(f"chaitin verify checkbox found and clicked at {coordinates}")
            await asyncio.sleep(uniform(0.05, 0.15))
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
