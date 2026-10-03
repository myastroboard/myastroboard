"""CPU compatibility smoke test, run inside the image by scripts/check_cpu_compat.sh.

Imports the app (which pulls in every dependency it uses) and exercises the hot
paths of the compiled libraries. On a CPU missing an instruction a wheel was built
for, the process dies with SIGILL - there is nothing to assert here beyond reaching
the end.
"""

import io
import sys
import types

sys.path.insert(0, "/app")

# backend.app skips its background schedulers (cache warm-up, SkyTonight, push) when
# pytest is loaded; without that they download ephemerides and crunch catalogues for
# minutes under emulation. The libraries they use are exercised directly below.
sys.modules.setdefault("pytest", types.ModuleType("pytest"))

import astropy.units as u  # noqa: E402
import backend.app  # noqa: E402,F401  - the import chain gunicorn workers run
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from astropy.coordinates import AltAz, EarthLocation, SkyCoord  # noqa: E402
from astropy.time import Time  # noqa: E402
from PIL import Image  # noqa: E402
from sgp4.api import Satrec, jday  # noqa: E402

rng = np.random.default_rng(0)
data = rng.random((300, 300))
np.sort(np.sqrt(np.abs(np.sin(data @ data))), axis=None)

frame = pd.DataFrame(data[:, :6])
frame.rolling(24).mean().sum()
frame.groupby((frame[0] * 10).astype(int)).mean()

location = EarthLocation(lat=45 * u.deg, lon=5 * u.deg, height=200 * u.m)
times = Time("2026-01-15 18:00") + np.linspace(0, 12, 48) * u.hour
SkyCoord(ra=83.82 * u.deg, dec=-5.39 * u.deg).transform_to(AltAz(obstime=times, location=location))

fig, ax = plt.subplots()
ax.plot(data[0])
fig.savefig(io.BytesIO(), format="png")

Image.fromarray((data * 255).astype(np.uint8)).resize((64, 64)).save(io.BytesIO(), format="PNG")

iss = Satrec.twoline2rv(
    "1 25544U 98067A   26001.50000000  .00016717  00000-0  30375-3 0  9990",
    "2 25544  51.6400 208.9163 0006317  69.9862  25.2906 15.49560832    09",
)
iss.sgp4(*jday(2026, 1, 1, 12, 0, 0))

print("cpu-compat smoke test: OK")
