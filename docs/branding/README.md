# OT Thermostat Control icon

A circular warm/cool thermostat dial with a central thermometer and radiant-heat strokes.
Created using the built-in image-generation tool. The transparent master is preserved as
`ot-thermostat-master.png`; the deployment files are PNG exports at 256 and 512 pixels.
Exports retain the generated alpha channel and use Lanczos downsampling.

The integration ships `brand/icon.png` and `brand/icon@2x.png`. Home Assistant 2026.3+
loads these directly, with its standard fallback for logo and dark-theme requests.
No manifest icon field or extra frontend resource is required.
[Home Assistant branding documentation](https://developers.home-assistant.io/docs/core/integration/brand_images/).

After installing the release through HACS, restart Home Assistant and refresh the frontend.
The local image endpoint is `/api/brands/integration/ot_thermostat_control/icon.png`;
it requires Home Assistant authentication. A HACS view that still uses the legacy remote
brands service may not show the locally bundled icon.

## Generation prompt

```
Use case: logo-brand. Asset type: square Home Assistant integration icon, production PNG with true transparent background. Primary request: create an original, polished icon for OT Thermostat Control, an operative-temperature thermostat integration balancing air temperature and radiant warmth. Subject: one very simple circular thermostat dial enclosing a bold thermometer symbol, with two short flowing radiant-heat strokes integrated beside the thermometer inside the dial. Warm and cool temperature cues, clean high-contrast colours that remain visible on both white and charcoal app backgrounds. Style: flat geometric app icon, crisp solid shapes, rounded ends, consistent substantial stroke weight, minimal details. Composition: single centred mark occupying about 85 percent of a square canvas; generous uniform clear margin, recognisable at 32 pixels. Output exactly 512 by 512 pixels if possible; actual transparent alpha outside the mark. No text, letters, numbers, gradients, shadows, textures, mockup, border tile or watermark. Do not imitate a hardware manufacturer's logo.
```
