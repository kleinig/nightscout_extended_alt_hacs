# Nightscout Extended Alt

A Home Assistant custom integration for Nightscout that consumes the Nightscout Socket.IO real-time feed.

## Current protocol coverage

The implementation is based on the captured Nightscout/AAPS Socket.IO traffic:

- Engine.IO / Socket.IO connection
- Main namespace `/`
- `/alarm` namespace
- `connected`
- `dataUpdate`
- `retroUpdate`
- `/alarm` `notification`
- `sgvs`
- `treatments`
- `devicestatus`
- treatment create/update/remove semantics
- reconnect with exponential backoff
- local de-duplicating caches keyed by Nightscout `_id`

Treatment handling is intentionally an upsert/remove model:

- no `action`: create/upsert
- `action: "update"`: replace the cached treatment by `_id`
- `action: "remove"`: remove the cached treatment by `_id`

## Configuration

Add the integration through **Settings → Devices & services → Add integration**.

Enter:

1. Nightscout URL
2. Readable access token if the site requires one
3. Preferred glucose display unit: `mg/dL` or `mmol/L`

The token is sent as the Nightscout `?token=` query parameter.

## Entities

The first version exposes:

- Glucose
- BG Delta
- IOB
- Basal IOB
- Insulin Activity
- COB
- Eventual BG
- Target BG
- Insulin Required
- Base Basal Rate
- Temp Basal Absolute Rate
- Temp Basal Remaining
- Reservoir
- Pump Battery
- AAPS Phone Battery
- Active Profile
- Pump Status
- Last Bolus Amount
- Socket Connected

The glucose-derived entities use the selected `mg/dL` / `mmol/L` display setting.

## Installation

Copy `custom_components/nightscout_extended_alt` into the Home Assistant `config/custom_components/` directory, restart Home Assistant, and add the integration from the UI.

For HACS, this repository can be added as a custom repository of type **Integration**.

## Important

This is an initial implementation, not a clinical or dosing application. It exposes the telemetry received from Nightscout and does not make dosing decisions.
