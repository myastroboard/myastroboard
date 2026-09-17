"""Browser end-to-end tests for the Observation Log sub-tab (v1.3).

This repo has no JS test framework, so these cover the parts of
`static/js/observation_sessions.js` that only a real browser exercises: the
sub-tab wiring, the DOM-built list/detail/modal rendering, and the automatic
"in Astrodex" badge that appears once a frame count is logged.
"""

import re

import pytest

pytestmark = pytest.mark.e2e

SUBTAB_BUTTON = '#astrodex-tab .sub-tab-btn[data-subtab="observation-log"]'


def _open_observation_log(page):
    """Navigate to Astrodex -> Observation Log and wait for the list to render."""
    page.click('.main-tab-btn[data-tab="astrodex"]')
    page.click(SUBTAB_BUTTON)
    page.wait_for_selector('#observation-log-new-session', state="visible")


def _create_session(page, date_value):
    """Drive the New Session modal.

    Creating a session drops straight into its detail view - the natural next step is
    logging what was captured - so this returns with the entry toolbar on screen, not
    the list.
    """
    page.click('#observation-log-new-session')
    page.wait_for_selector('#observation-session-form', state="visible")
    page.fill('#observation-session-date', date_value)
    page.fill('#observation-session-notes', 'clear and cold')
    page.click('#observation-session-form button[type="submit"]')
    page.wait_for_selector('#observation-log-add-target', state="visible")


def test_observation_log_subtab_renders_without_console_errors(logged_in_page):
    """Opening the sub-tab must render its stats + list with a clean console.

    A syntax error or a missing global in observation_sessions.js surfaces here and
    nowhere else - the Python suite never loads the file.
    """
    page = logged_in_page
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    _open_observation_log(page)

    assert page.locator('#observation-log-stats .stat-plate-hero-value').count() == 1
    assert page.locator('#observation-log-stats .stat-plate-figure').count() == 3
    assert not errors, f"Console/page errors on the Observation Log sub-tab: {errors}"


def test_subtab_switch_updates_the_url_hash(logged_in_page):
    """The 5th Astrodex sub-tab routes through the generic switchSubTab() path."""
    page = logged_in_page

    page.click('.main-tab-btn[data-tab="astrodex"]')
    page.click(SUBTAB_BUTTON)
    page.wait_for_url(re.compile(r"#astrodex/observation-log"))

    assert "#astrodex/observation-log" in page.url


def test_create_session_then_log_a_target_links_it_to_astrodex(logged_in_page):
    """Full happy path: create a session, add a target with frames, see the Astrodex badge.

    The badge is the user-visible proof of the automatic item registration - the entry
    is never pushed to Astrodex by a button, only by having a frame count.
    """
    page = logged_in_page
    _open_observation_log(page)
    _create_session(page, '2026-07-14')

    page.click('#observation-log-add-target')
    page.wait_for_selector('#observation-entry-form', state="visible")
    page.fill('#observation-entry-name', 'M31')
    page.select_option('#observation-entry-type', 'Galaxy')
    page.fill('#observation-entry-frames', '42')
    page.click('#observation-entry-form button[type="submit"]')

    page.wait_for_selector('.observation-log-entry-row', state="visible")
    # The catalogue search box is separate from the Name field (mirroring Astrodex's
    # add-item modal), so typing straight into Name is not overwritten by a lookup.
    assert page.locator('.observation-log-entry-name').first.inner_text().strip() == 'M31'
    assert page.locator('.observation-log-entry-row .badge.bg-secondary', has_text='42').count() >= 1
    # frame_count > 0 -> the target is now registered in Astrodex, with no user action
    page.wait_for_selector('.observation-log-entry-row .badge.bg-success', state="visible")


def test_export_session_pdf_downloads_a_file(logged_in_page):
    """The per-session 'Export PDF' button on the detail view produces a real download."""
    page = logged_in_page
    _open_observation_log(page)
    _create_session(page, '2026-07-14')

    with page.expect_download() as download_info:
        page.click('#observation-log-export-pdf')
    download = download_info.value

    assert download.suggested_filename.endswith('.pdf')
    saved_path = download.path()
    assert saved_path is not None
    with open(saved_path, 'rb') as pdf_file:
        assert pdf_file.read(4) == b'%PDF'


def test_export_all_pdf_modal_prefills_range_and_downloads(logged_in_page):
    """The list-view 'Export all (PDF)' button opens the range/order modal, prefilled
    with the session's own date, and submitting it downloads a real PDF."""
    page = logged_in_page
    _open_observation_log(page)
    _create_session(page, '2026-07-14')

    page.click('#observation-log-back')
    page.wait_for_selector('#observation-log-export-all', state="visible")
    page.click('#observation-log-export-all')

    page.wait_for_selector('#observation-export-pdf-form', state="visible")
    assert page.input_value('#observation-export-pdf-from') == '2026-07-14'
    assert page.input_value('#observation-export-pdf-to') == '2026-07-14'

    with page.expect_download() as download_info:
        page.click('#observation-export-pdf-form button[type="submit"]')
    download = download_info.value

    assert download.suggested_filename.endswith('.pdf')
    saved_path = download.path()
    assert saved_path is not None
    with open(saved_path, 'rb') as pdf_file:
        assert pdf_file.read(4) == b'%PDF'


def test_filters_narrow_the_session_list(logged_in_page):
    """The client-side search filter refreshes only the results container."""
    page = logged_in_page
    _open_observation_log(page)
    _create_session(page, '2026-03-02')

    # Back out of the detail view the create flow left us in
    page.click('#observation-log-back')
    page.wait_for_selector('#observation-log-search', state="visible")

    page.fill('#observation-log-search', 'definitely-no-such-session')
    page.wait_for_selector('.observation-log-empty', state="visible")
    assert page.locator('.observation-log-session-card').count() == 0

    # The search box keeps focus and content across a filter refresh
    assert page.input_value('#observation-log-search') == 'definitely-no-such-session'

    page.fill('#observation-log-search', '')
    page.wait_for_selector('.observation-log-session-card', state="visible")


def test_add_second_night_groups_entries_and_shows_night_selector(logged_in_page):
    """A multi-night session gets a second Nights card, and the entry form gains a
    night selector (hidden for the single-night case) once there's more than one."""
    page = logged_in_page
    _open_observation_log(page)
    _create_session(page, '2026-07-14')

    # Log a target on the first night before adding the second, to prove entries stay
    # correctly attributed to their own night once grouping kicks in.
    page.click('#observation-log-add-target')
    page.wait_for_selector('#observation-entry-form', state="visible")
    page.fill('#observation-entry-name', 'M31')
    page.select_option('#observation-entry-type', 'Galaxy')
    page.click('#observation-entry-form button[type="submit"]')
    page.wait_for_selector('.observation-log-entry-row', state="visible")

    page.click('#observation-log-add-night')
    page.wait_for_selector('#observation-night-form', state="visible")
    page.fill('#observation-night-date', '2026-07-15')
    page.click('#observation-night-form button[type="submit"]')
    # A .observation-log-night-card for the first night already exists, so waiting on
    # that selector alone would resolve immediately - wait for the *new* night's own
    # date to actually render instead, to properly synchronize on the reload.
    page.wait_for_selector('.observation-log-night-date:has-text("2026-07-15")', state="visible")
    assert page.locator('.observation-log-night-card').count() == 2

    page.click('#observation-log-add-target')
    page.wait_for_selector('#observation-entry-form', state="visible")
    assert page.locator('#observation-entry-night option').count() == 2
    page.select_option('#observation-entry-night', label='2026-07-15')
    page.fill('#observation-entry-name', 'M42')
    page.select_option('#observation-entry-type', 'Nebula')
    page.click('#observation-entry-form button[type="submit"]')

    # Entries are now grouped by night - one date divider per night with targets.
    # (M31's row already existed, so wait on M42's own name rather than the row
    # selector alone, to properly synchronize on the reload finishing.)
    page.wait_for_selector('.observation-log-entry-name:has-text("M42")', state="visible")
    assert page.locator('.observation-log-entry-row').count() == 2
    assert page.locator('.observation-log-night-date', has_text='2026-07-14').count() == 1
    assert page.locator('.observation-log-night-date', has_text='2026-07-15').count() == 1


def test_upload_and_delete_a_session_attachment(logged_in_page):
    """A generic file (not a photo through the Astrodex picture flow) can be attached to
    the session and removed again."""
    page = logged_in_page
    _open_observation_log(page)
    _create_session(page, '2026-07-14')

    page.click('#observation-log-back')
    page.wait_for_selector('.observation-log-session-card', state="visible")
    page.click('.observation-log-session-card')
    page.wait_for_selector('#observation-log-add-attachment', state="visible")

    page.click('#observation-log-add-attachment')
    page.wait_for_selector('#observation-attachment-form', state="visible")
    page.set_input_files(
        '#observation-attachment-file',
        {'name': 'guide-log.txt', 'mimeType': 'text/plain', 'buffer': b'guiding data'},
    )
    page.click('#observation-attachment-form button[type="submit"]')
    page.wait_for_selector('text=guide-log.txt', state="visible")

    page.once('dialog', lambda dialog: dialog.accept())
    page.click('.list-group-item button.btn-outline-danger')
    page.wait_for_selector('text=guide-log.txt', state="detached")
