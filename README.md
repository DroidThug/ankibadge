# Anki macOS Dock Badge

An Anki add-on for macOS that displays your total due card count (New + Learning + Review) as a numeric badge on the Anki Dock icon.

## Features

- Shows total cards due across all decks as a Dock badge
- Clears the badge automatically when no cards are due
- Updates after answering a card, finishing a sync, or loading a collection
- Compatible with Anki 24+ (Qt6), V3 scheduler, and FSRS
- Falls back to a `ctypes`-based Objective-C bridge if PyObjC is unavailable

## Limitations

- **macOS only** — does nothing on Windows or Linux
- The badge disappears when Anki is closed; this is a macOS limitation (badges are owned by the running process)

## Installation

### Manual

1. Download or clone this repository
2. Copy the `ankibadge` folder to your Anki add-ons directory:
   ```
   cp -r ankibadge ~/Library/Application\ Support/Anki2/addons21/ankibadge
   ```
3. Restart Anki

### Via AnkiWeb

Search for **Dock Badge** on [AnkiWeb](https://ankiweb.net/shared/addons).

## Requirements

- macOS
- Anki 24.x or later

## Disclaimer

> This add-on was written with the assistance of Claude (Anthropic's AI assistant). It has been tested and works as described, but is provided as-is with no warranty. Use at your own risk.

## License

MIT
