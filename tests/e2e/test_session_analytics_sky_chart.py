"""Browser end-to-end tests for the Analytics sky coverage chart (v1.5).

This repo has no JS test framework, and the sky chart is the part of
`static/js/session_analytics.js` that a Python test cannot reach at all: the Milky Way and
the ecliptic are painted by a Chart.js plugin straight onto a canvas, and the month axis is
a scale that no dataset refers to - Chart.js draws it only because it is asked to. A
Chart.js upgrade could drop either one without a single Python test noticing.
"""

import pytest

pytestmark = pytest.mark.e2e

SUBTAB_BUTTON = '#astrodex-tab .sub-tab-btn[data-subtab="analytics"]'
COVERAGE_CANVAS = '#sessionAnalyticsCoverageChart'

# Each target, the integration recorded for it, and the month it is at its best. The months
# were checked against the Sun's real right ascension through Astropy, not against the
# formula under test.
#
# The coordinates are seeded explicitly: this suite runs against an empty temp DATA_DIR
# with no SkyTonight dataset to look names up in, so a target carrying no position of its
# own would be counted as unplaced and would never reach the chart. Right ascension goes in
# as decimal hours, which is the shape the SkyTonight target cards send.
SEEDED_TARGETS = [
    {'name': 'M 31', 'catalogue': 'Messier', 'integration_minutes': 240,
     'ra': 0.712, 'dec': 41.269, 'best_month': 10},
    {'name': 'M 42', 'catalogue': 'Messier', 'integration_minutes': 30,
     'ra': 5.588, 'dec': -5.391, 'best_month': 12},
    {'name': 'M 13', 'catalogue': 'Messier', 'integration_minutes': 90,
     'ra': 16.695, 'dec': 36.460, 'best_month': 6},
]


def _seed_a_captured_session(page, base_url):
    """Give the logged-in user one session holding every SEEDED_TARGETS entry."""
    created = page.request.post(f"{base_url}/api/observation-sessions", data={'date': '2026-09-01'})
    assert created.ok, f"could not create the session: {created.status} {created.text()}"
    session_id = created.json()['data']['id']

    for target in SEEDED_TARGETS:
        added = page.request.post(
            f"{base_url}/api/observation-sessions/{session_id}/entries",
            data={
                'name': target['name'],
                'catalogue': target['catalogue'],
                'integration_minutes': target['integration_minutes'],
                'ra': target['ra'],
                'dec': target['dec'],
                'rating': 4,
            },
        )
        assert added.ok, f"could not add {target['name']}: {added.status} {added.text()}"


def _open_analytics(page):
    """Navigate to Astrodex -> Analytics and wait for the sky chart to be on screen."""
    page.click('.main-tab-btn[data-tab="astrodex"]')
    page.click(SUBTAB_BUTTON)
    page.wait_for_selector(COVERAGE_CANVAS, timeout=30000)


def test_best_month_reading_matches_the_real_sun(logged_in_page):
    """An object culminates near midnight when the Sun sits half a sky away from it.

    Reading that off one straight line through the year is out by up to five days, which
    lands on the wrong side of a month boundary for anything near one - hence the
    equinox/solstice anchors. These expectations come from Astropy's own Sun positions.
    """
    page = logged_in_page

    for right_ascension_hours, expected_month in (
        (0.71, 10),   # M 31
        (5.59, 12),   # M 42
        (13.50, 4),   # M 51
        (16.69, 6),   # M 13
        (18.89, 7),   # M 57
        (0.0, 9),
        (12.0, 3),
    ):
        reading = page.evaluate("hours => _saBestMonth(hours)", right_ascension_hours)
        assert reading == expected_month, (
            f"RA {right_ascension_hours}h should read as month {expected_month}, got {reading}"
        )


def test_best_month_reading_survives_a_missing_right_ascension(logged_in_page):
    """The axis callback runs on whatever the scale hands it, so it must not throw."""
    for value in (None, 'not a number', float('nan')):
        assert 1 <= logged_in_page.evaluate("value => _saBestMonth(value)", value) <= 12


def test_sky_chart_renders_with_its_month_axis(logged_in_page, live_server_url):
    """The top axis is a scale no dataset refers to - the one thing most likely to vanish.

    Its labels have to be real month names, and it has to span the same reversed right
    ascension as the axis below it, or the two disagree about where the sky is.
    """
    page = logged_in_page
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    _seed_a_captured_session(page, live_server_url)
    _open_analytics(page)

    month_axis = page.evaluate(
        "() => {"
        "  const chart = sessionAnalyticsCharts.sessionAnalyticsCoverageChart;"
        "  const scale = chart && chart.scales.x2;"
        "  return scale ? {labels: scale.ticks.map(t => t.label), min: scale.min, max: scale.max,"
        "                  reverse: scale.options.reverse} : null;"
        "}"
    )
    assert month_axis is not None, "the month axis is gone - Chart.js dropped the dataset-less scale"
    assert month_axis['min'] == 0 and month_axis['max'] == 24
    assert month_axis['reverse'] is True
    assert len(month_axis['labels']) >= 5
    assert all(str(label).strip() for label in month_axis['labels'])
    # Both ends of the axis are the same point in the sky, so they must read the same month.
    assert month_axis['labels'][0] == month_axis['labels'][-1]

    assert not errors, f"Console/page errors on the Analytics sub-tab: {errors}"


def test_a_longer_integration_gets_a_bigger_dot(logged_in_page, live_server_url):
    """Dot size is the only place integration time shows up on the chart itself."""
    page = logged_in_page
    _seed_a_captured_session(page, live_server_url)
    _open_analytics(page)

    radii_by_name = page.evaluate(
        "() => {"
        "  const dataset = sessionAnalyticsCharts.sessionAnalyticsCoverageChart.data.datasets[0];"
        "  const sizes = {};"
        "  dataset.data.forEach((item, index) => { sizes[item.point.name] = dataset.pointRadius[index]; });"
        "  return sizes;"
        "}"
    )

    longest = max(SEEDED_TARGETS, key=lambda target: target['integration_minutes'])['name']
    shortest = min(SEEDED_TARGETS, key=lambda target: target['integration_minutes'])['name']
    assert radii_by_name[longest] > radii_by_name[shortest]


def test_the_backdrop_takes_its_colours_from_the_stylesheet(logged_in_page, live_server_url):
    """A canvas cannot carry a class, so the palette is read back from custom properties.

    Hardcoding it in JS would paint a blue sky over the red night-vision theme.
    """
    page = logged_in_page
    _seed_a_captured_session(page, live_server_url)
    _open_analytics(page)

    def backdrop():
        return page.evaluate(
            "() => sessionAnalyticsCharts.sessionAnalyticsCoverageChart"
            ".options.plugins.sessionAnalyticsSkyBackdrop"
        )

    default_theme = backdrop()
    assert default_theme['backgroundTop'], "the sky chart has no background colour"

    page.evaluate("document.documentElement.setAttribute('data-theme', 'red')")
    page.evaluate("_saRenderCoverage(sessionAnalyticsData.coverage)")
    red_theme = backdrop()

    assert red_theme['backgroundTop'] != default_theme['backgroundTop'], (
        "the red night-vision theme reuses the default sky colour"
    )
