"""Browser end-to-end tests for the shared modal machinery (utils.js openModal /
closeModal / forceCleanupModals / the modal <-> history bridge).

These only show up in a real browser: Bootstrap's backdrop / body-scroll-lock
lifecycle, the hardware Back button closing a modal instead of switching tabs,
and the "close whatever is open before showing the next one" rule that keeps
Bootstrap 5.3 (which cannot stack modals) from stranding a backdrop.

Run at a phone-sized viewport - the reported problems were mobile-only. Tab
navigation is driven through switchMainTab()/switchSubTab() rather than the
navbar, which is collapsed behind a hamburger at this width.
"""

import pytest

pytestmark = pytest.mark.e2e

MOBILE_VIEWPORT = {"width": 390, "height": 844}


def _residue(page):
    """Everything modal-related that could be left hanging on the page."""
    return page.evaluate("""() => ({
            backdrops: document.querySelectorAll('.modal-backdrop').length,
            shown: document.querySelectorAll('.modal.show').length,
            bodyLocked: document.body.classList.contains('modal-open'),
            bodyOverflow: document.body.style.overflow,
        })""")


def _goto_astrodex(page):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.evaluate("switchMainTab('astrodex')")
    page.wait_for_selector('#add-astrodex-item', state="visible")


def _open_shared_modal(page, settled=True):
    page.evaluate("showAddAstrodexItemModal()")
    page.wait_for_selector('#modal_lg_close.show', state="visible")
    if settled:
        page.wait_for_selector('#modal_lg_close[data-mab-settled="true"]')


def test_close_via_header_x_leaves_no_backdrop_or_scroll_lock(logged_in_page):
    """The classic mobile bug: after closing certain modals the page stayed frozen
    (body kept `modal-open` / `overflow:hidden`) or a blur layer lingered."""
    page = logged_in_page
    _goto_astrodex(page)
    _open_shared_modal(page)

    page.click('#modal_lg_close .btn-close')
    page.wait_for_selector('#modal_lg_close.show', state="detached")
    page.wait_for_function("() => document.querySelectorAll('.modal-backdrop').length === 0")

    assert _residue(page) == {
        "backdrops": 0,
        "shown": 0,
        "bodyLocked": False,
        "bodyOverflow": "",
    }


def test_close_immediately_after_open_is_not_swallowed(logged_in_page):
    """Bootstrap's hide() is a silent no-op mid show-transition - a close fired
    right after open used to leave the modal stuck. The helper defers the hide
    until the show settles."""
    page = logged_in_page
    _goto_astrodex(page)
    _open_shared_modal(page, settled=False)

    # No settle wait - hit it while the show transition is still running.
    page.evaluate("closeModal('#modal_lg_close')")

    page.wait_for_selector('#modal_lg_close.show', state="detached", timeout=8000)
    page.wait_for_function("() => document.querySelectorAll('.modal-backdrop').length === 0")
    assert not _residue(page)["bodyLocked"]


def test_back_button_closes_the_modal_and_keeps_the_tab(logged_in_page):
    """Android Back / iOS swipe-back must dismiss the modal, not navigate the tab
    out from under it."""
    page = logged_in_page
    _goto_astrodex(page)
    _open_shared_modal(page)

    page.go_back()

    page.wait_for_selector('#modal_lg_close.show', state="detached")
    page.wait_for_function("() => document.querySelectorAll('.modal-backdrop').length === 0")
    assert page.locator('.main-tab-btn.active').get_attribute("data-tab") == "astrodex"
    residue = _residue(page)
    assert residue["backdrops"] == 0 and residue["shown"] == 0 and not residue["bodyLocked"]


def test_opening_a_second_modal_closes_the_first_no_stacked_backdrops(logged_in_page):
    """openModal() fully closes whatever is on screen first - exactly one modal and
    one backdrop at a time, and the body stays scroll-locked throughout."""
    page = logged_in_page
    _goto_astrodex(page)
    _open_shared_modal(page)

    page.evaluate("showObjectInfoModal('M42')")

    page.wait_for_function("""() => {
            const shown = document.querySelectorAll('.modal.show');
            return shown.length === 1 && shown[0].id === 'modal_lg_close'
                && document.querySelectorAll('.modal-backdrop').length === 1
                && document.body.classList.contains('modal-open');
        }""")

    page.evaluate("closeModal('#modal_lg_close')")
    page.wait_for_function("() => document.querySelectorAll('.modal-backdrop').length === 0")
    residue = _residue(page)
    assert not residue["bodyLocked"] and residue["bodyOverflow"] == ""


def test_switching_tab_with_a_modal_open_closes_it_cleanly(logged_in_page):
    """A modal left open across a tab change would float over the wrong tab or
    strand its backdrop - switchMainTab() now closes it first."""
    page = logged_in_page
    _goto_astrodex(page)
    _open_shared_modal(page)

    page.evaluate("switchMainTab('spaceflight')")

    page.wait_for_selector('#modal_lg_close.show', state="detached")
    page.wait_for_function("() => document.querySelectorAll('.modal-backdrop').length === 0")
    assert page.locator('.main-tab-btn.active').get_attribute("data-tab") == "spaceflight"
    residue = _residue(page)
    assert not residue["bodyLocked"] and residue["bodyOverflow"] == ""


def test_modal_open_does_not_change_the_url_hash(logged_in_page):
    """The synthetic history entry must carry the current URL so Back/Forward over
    it never fires `hashchange` (which would move tabs)."""
    page = logged_in_page
    _goto_astrodex(page)
    url_before = page.url

    _open_shared_modal(page)

    assert page.url == url_before
