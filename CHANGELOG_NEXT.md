#### Introduce Connectors & Observatory

Connect external astronomy tools to MyAstroBoard and view their live data in the new Observatory tab.

- **Observatory tab**: live dashboard fed by enabled connectors — hidden until at least one connector is active
- **AllSky connector**: integrates with an [AllSky](https://github.com/AllskyTeam/allsky) all-sky camera (v2024.12+)
  - Live image with 30 s auto-refresh
  - Sensor data (temperature, humidity, gain, exposure, brightness) via AllSky Export module
  - Keogram, startrails and daily timelapse
  - All resources proxied through the backend — works behind HTTPS reverse proxies
- **Connector framework**: extensible architecture (`BaseConnector`) for adding future integrations

#### Various

- Notification for aurora with better localization and cooldown.
- Add forecast night with score for a quick information
- Improve hero cards for astro score
- Improve cards weather/moon/aurora
- Improve tests and code quality
