# Nest Thermostat

Control a Google Nest thermostat from your eisy using **your own** Google Device Access project.

## Tested
Version 1.0.1 was tested by its owner on a real Nest Learning Thermostat (3rd generation) on a regular consumer Google account. Confirmed working: reading the thermostat, the heat target, the cool target, mode changes and Eco on/off. Other Nest models and Google Workspace accounts were not tested.

## What you get
- Current temperature and humidity
- Mode: Off / Heat / Cool / Heat-Cool (readable and settable)
- Heat and cool target temperatures (readable and settable)
- Whether the system is currently heating or cooling
- Eco mode on/off (settable)
- Online/offline status

Temperatures follow the scale set on the thermostat (°F or °C). Google only accepts Celsius for commands, so the plugin converts.

## Limits (from Google's documentation)
- While Eco is on, Google rejects temperature-target changes and does not report the targets.
- To change the heat target the thermostat must be in Heat mode, the cool target needs Cool mode, and in Heat/Cool mode both targets are set together.
- The thermostat's display scale cannot be changed through the API.
- No Home/Away control was found in Google's thermostat documentation. Eco is offered instead.

## Requirements
- A Device Access project already set up with Google (this plugin cannot create one), with an OAuth client linked to it and a consumer Google account that owns the thermostat. Google charges a one-time registration fee for Device Access.
- The OAuth consent screen set to "In production" (in "Testing" status Google expires sign-ins after 7 days).

## Setup
After install, open the plugin's configuration page and fill in `project_id`, `client_id` and `client_secret`, then follow the on-page notes to get a one-time `auth_code` and paste it in. The plugin stores its own long-lived sign-in privately in its `persist/` folder on your eisy. Never share your client secret or that folder.

## Polling
State is refreshed every 5 minutes and right after each command. Google's request limits were not confirmed, so the interval is deliberately conservative. Event push (Pub/Sub) is not used.

## License Notice

This plugin's development referenced the following source(s), whose license is not on the standard permissive allowlist. Review their license terms before relying on or redistributing this plugin:

- [GitHub - michaelkorby/nest_thermostat_logger: Log temperatures from all the nest sensors · GitHub](https://github.com/michaelkorby/nest_thermostat_logger) -- license: unknown
- [GitHub - chriseng/nestgraph: Create pretty charts of your Nest thermostat data · GitHub](https://github.com/chriseng/nestgraph) -- license: unknown

See LICENSE.md for full third-party attribution.
