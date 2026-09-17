"""Browser end-to-end tests for the shared headline-figures plate (DOMUtils.buildStatPlate).

Three tabs render their headline numbers through it, and none of them can be reached from
a Python test: the plate is built in the browser from data the page has already fetched.

Every test here runs as an account created for it, so the first-run case is genuinely
empty. The e2e DATA_DIR is shared across the whole pytest session rather than reset per
test, so "the default admin has logged nothing" stops being true the moment any earlier
test logs something - and one of them does. A first run is where a renderer that assumes
its data exists falls over, and it is the one state every user passes through.
"""

import uuid

import pytest

pytestmark = pytest.mark.e2e

PLATES = [
    ('astrodex', '#astrodex-stats', 4),
    ('observation-log', '#observation-log-stats', 3),
    ('analytics', '#session-analytics-stats', 7),
]


@pytest.fixture
def fresh_user_page(page, live_server_url, login):
    """A page logged in as a brand new account that has never logged anything."""
    login(page, live_server_url)
    username = 'plate_%s' % uuid.uuid4().hex[:8]
    created = page.request.post(
        f"{live_server_url}/api/users",
        data={'username': username, 'password': 'plate-test-pw', 'role': 'user'},
    )
    assert created.ok, f"could not create the account: {created.status} {created.text()}"

    logged_out = page.request.post(f"{live_server_url}/api/auth/logout")
    assert logged_out.ok, logged_out.text()
    login(page, live_server_url, username=username, password='plate-test-pw')
    return page


def _open_astrodex_subtab(page, subtab):
    """Navigate to Astrodex, and to one of its sub-tabs when it is not the default one."""
    page.click('.main-tab-btn[data-tab="astrodex"]')
    if subtab != 'astrodex':
        page.click(f'#astrodex-tab .sub-tab-btn[data-subtab="{subtab}"]')


@pytest.mark.parametrize('subtab, selector, figures', PLATES)
def test_plate_renders_on_an_account_with_nothing_logged(fresh_user_page, subtab, selector, figures):
    """A brand new account has to get a plate of zeros, not an empty box or a stack trace."""
    page = fresh_user_page
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    _open_astrodex_subtab(page, subtab)
    page.wait_for_selector(f'{selector}.stat-plate', timeout=30000)

    assert page.locator(f'{selector} .stat-plate-hero-value').count() == 1
    assert page.locator(f'{selector} .stat-plate-figure').count() == figures
    assert not errors, f"Console/page errors on the {subtab} plate: {errors}"


@pytest.mark.parametrize('subtab, selector, figures', PLATES)
def test_every_figure_on_an_empty_plate_says_something(fresh_user_page, subtab, selector, figures):
    """No figure may come out blank, "NaN" or "undefined" for want of data."""
    page = fresh_user_page
    _open_astrodex_subtab(page, subtab)
    page.wait_for_selector(f'{selector}.stat-plate', timeout=30000)

    values = page.locator(f'{selector} .stat-plate-hero-value, {selector} .stat-plate-value').all_inner_texts()
    assert len(values) == figures + 1
    for value in values:
        assert value.strip(), f"{subtab}: a figure rendered empty"
        assert 'NaN' not in value, f"{subtab}: a figure rendered NaN"
        assert 'undefined' not in value, f"{subtab}: a figure rendered undefined"
        assert 'null' not in value, f"{subtab}: a figure rendered null"


@pytest.mark.parametrize('subtab, selector', [
    ('observation-log', '#observation-log-stats'),
    ('analytics', '#session-analytics-stats'),
])
def test_a_zero_duration_still_carries_its_unit(fresh_user_page, subtab, selector):
    """The hero of both logbook plates is a duration.

    A bare "0" under "Light collected" does not say zero of what, and at the hero's size
    that is the first thing a new user reads.
    """
    page = fresh_user_page
    _open_astrodex_subtab(page, subtab)
    page.wait_for_selector(f'{selector}.stat-plate', timeout=30000)

    hero = page.locator(f'{selector} .stat-plate-hero-value').inner_text().strip()
    assert hero != '0', f"{subtab}: the hero duration lost its unit"
    assert any(character.isalpha() for character in hero), (
        f"{subtab}: expected a unit alongside the number, got {hero!r}"
    )


def test_the_log_driven_sections_show_their_empty_states(fresh_user_page):
    """Everything derived from the log explains itself rather than drawing an empty chart."""
    page = fresh_user_page
    _open_astrodex_subtab(page, 'analytics')
    page.wait_for_selector('#session-analytics-stats.stat-plate', timeout=30000)

    for container in ('#session-analytics-charts', '#session-analytics-coverage',
                      '#session-analytics-conditions'):
        page.wait_for_selector(f'{container} .session-analytics-empty', timeout=30000)
        assert page.locator(f'{container} .session-analytics-empty').inner_text().strip(), (
            f"{container}: empty state rendered with no message"
        )
        assert page.locator(f'{container} canvas').count() == 0, (
            f"{container}: a chart was drawn on data that is not there"
        )


def test_best_months_is_useful_before_anything_has_been_logged(fresh_user_page):
    """Best months is the one section that does not wait for a log.

    Its bars are available darkness and moonless darkness, computed from the Sun and the
    Moon at the active location; only the overlaid line comes from the user's own nights.
    So a brand new account already gets a real answer here, and turning this into an empty
    state would throw away the one thing the page can say on day one.
    """
    page = fresh_user_page
    _open_astrodex_subtab(page, 'analytics')
    page.wait_for_selector('#session-analytics-best-months canvas', timeout=30000)

    assert page.locator('#session-analytics-best-months .session-analytics-empty').count() == 0
    chart = page.evaluate(
        "() => {"
        "  const instance = sessionAnalyticsCharts.sessionAnalyticsBestMonthsChart;"
        "  return instance ? instance.data.datasets.map(set => set.data.length) : null;"
        "}"
    )
    assert chart, "the best months chart was not built"
    assert max(chart) == 12, f"expected a full year of months, got {chart}"
