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
    # DDoS-GUARD
    'DDoS-Guard'
]

CHALLENGE_SELECTORS = [
    # Cloudflare
    '#cf-challenge-running', '.ray_id', '.attack-box',
    '#cf-please-wait', '#challenge-spinner', '#trk_jschal_js', '#turnstile-wrapper', '.lds-ring',
    # Custom CloudFlare for EbookParadijs, Film-Paleis, MuziekFabriek and Puur-Hollands
    'td.info #js_info',
    # Fairlane / pararius.com
    'div.vc div.text-box h2'
]
SHORT_TIMEOUT = 10
CF_TIMEOUT = int(os.getenv("NASTOOL_CF_TIMEOUT", "60"))


async def resolve_challenge(tab: Tab, timeout=CF_TIMEOUT):
    start_ts = time.time()
    try:
        await asyncio.wait_for(_evil_logic(tab), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        log.error(f'Error solving the challenge. Timeout {timeout} after {round(time.time() - start_ts, 1)} seconds.')
        return False
    except Exception as e:
        log.error('Error solving the challenge. ' + str(e))
        return False


def under_challenge(html_text: str):
    """
    Check if the page is under challenge
    :param html_text:
    :return:
    """
    # get the page title
    if not html_text:
        return False
    page_title = PyQuery(html_text)('title').text()
    log.debug("under_challenge page_title=" + page_title)
    for title in CHALLENGE_TITLES:
        if page_title.lower() == title.lower():
            return True
    for selector in CHALLENGE_SELECTORS:
        html_doc = PyQuery(html_text)
        if html_doc(selector):
            return True
    return False

@staticmethod
async def check_document_ready(tab:Tab):
    while await tab.evaluate('document.readyState') != 'complete':
        await tab.sleep(1)
    return True

async def _until_match_func(tab: Tab, item, match_func, async_type=True):
    if async_type:
        while not await match_func(tab, item):
            await tab.sleep(0.1)
    else:
        while not match_func(tab, item):
            await tab.sleep(0.1)
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
        await asyncio.wait_for(check_document_ready(tab), SHORT_TIMEOUT)
    except asyncio.TimeoutError:
        log.debug("Timeout waiting for the page")

    # find access denied titles and selectors
    if await _any_match_titles(tab, ACCESS_DENIED_TITLES) or await _any_match_selectors(tab, ACCESS_DENIED_SELECTORS):
        raise Exception('Cloudflare has blocked this request. Probably your IP is banned for this site, check in your web browser.')

    # find challenge by titles and selectors
    challenge_found = await _any_match_titles(tab, CHALLENGE_TITLES) or await _any_match_selectors(tab, CHALLENGE_SELECTORS)

    if challenge_found:
        # wait until the title changes
        # then wait until all the selectors disappear
        while not (await _wait_until_condition(tab, CHALLENGE_TITLES, lambda d, t: d.target.title.lower() != t.lower(), async_type=False, message="title changes") and
                   await _wait_until_condition(tab, CHALLENGE_SELECTORS, async_match_selectors_not, async_type=True, message="selectors disappear")):
            log.debug("Timeout waiting for selector")
            await click_verify(tab)

        # waits until Cloudflare redirection ends
        log.debug("Waiting for redirect")
        try:
            await tab
        except Exception:
            log.debug("Timeout waiting for redirect")

        log.info("Challenge solved!")
    else:
        log.info("Challenge not detected!")


async def click_verify(tab: Tab):
    from app.helper import ChromeHelper
    try:
        log.debug("Try to find the Cloudflare verify checkbox")
        selector = "input[type=checkbox]"
        await ChromeHelper.find_and_click_element(tab=tab, selector=selector)
        log.debug("Cloudflare verify checkbox found and clicked")
    except Exception as e:
        log.debug(f"Cloudflare verify checkbox not found: {str(e)}")

    await asyncio.wait_for(check_document_ready(tab), SHORT_TIMEOUT)
