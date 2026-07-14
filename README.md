# Electrolux AC — Home Assistant integration

Control Electrolux (and Electrolux-brand, e.g. Frigidaire) air conditioners in
Home Assistant through the official Electrolux Group Developer API, with
real-time updates over SSE.

> Not affiliated with, developed, or supported by Electrolux.

## Features

- `climate` entity: on/off, modes (cool/auto/dry/fan-only), target temperature,
  fan speed, vertical swing — all driven by what your unit reports as supported.
- Sensors: ambient temperature, filter state, Wi-Fi signal.
- Switches: sleep mode, clean air, panel lock, scheduler, display light.
- Connectivity binary sensor.
- Real-time push via the Electrolux livestream (SSE) with a 5-minute
  reconciliation poll.

## Requirements

An Electrolux developer API key and JWT tokens. Get them at
[developer.electrolux.one](https://developer.electrolux.one):

1. Sign in with your Electrolux app account.
2. Create an API key on the dashboard.
3. Generate an access token + refresh token.

## Installation (HACS)

1. In HACS → Integrations → three-dot menu → **Custom repositories**.
2. Add `https://github.com/lbkeppler/eletrolux-ac` with category **Integration**.
3. Install **Electrolux AC**, then restart Home Assistant.
4. Settings → Devices & Services → **Add Integration** → **Electrolux AC**.
5. Paste your API key, access token, and refresh token.

## Notes

- Free tier limits: 10 req/s, 5000 req/day, one SSE channel. The integration
  uses a single SSE connection plus a 5-minute poll, well within the quota.
- Tokens are stored in Home Assistant and refreshed automatically; if refresh
  fails you'll be prompted to re-authenticate.
