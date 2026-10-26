# Colour themes

The web app's colours are a theme. Gold is the built-in theme. Your install can add more, and you can make one of your own.

## Choosing a theme

Open **Settings** in the top bar (on a phone: **More**). Between **Theme** and **Language** there is a **Colours** row with one round button per theme. Hover a button to see its name. The app changes colour at once, and your choice is remembered in this browser.

If your last choice no longer exists, the app uses your install's default theme, or gold if there is none.

## Making your own theme

Click the dashed **My theme** button. In the dialog:

1. Give it a **Name**.
2. Pick an **Accent** colour. It colours buttons, selected items and links.
3. Optionally pick a **Background** colour, the dark page colour. The light page takes its hue. **Auto** clears it, and the greys come from the tone.
4. Choose a **Tone** for the greys when there is no background: Neutral (pure grey), Warm (beige) or Cool (blue-grey).

The preview on the right shows a small page in your colours. Its sun / moon switch shows light or dark. A note warns you about a pair that is hard to read. **Save and use** applies the theme.

You get one theme per browser. Click its button to use it, the small pencil to edit it, and **Delete** in the dialog to remove it. The theme is stored in this browser only. It does not follow you to another browser or computer.

Success, failure and warning colours (green, red, amber) are the same in every theme.

## Font

The Settings menu has a **Font** row under Colours, with three buttons, each shown in its own font:

- **Classic** (Arial, the default, nothing to download)
- **Inter**
- **Atkinson Hyperlegible**, which is easier to read at a glance

Your choice is saved in your browser and works with every colour theme. A provided theme may set a font too, but your own pick wins over it.

<div data-technical>

A provided theme can set `"font": "classic"`, `"inter"` or `"atkinson"`.

</div>

## Themes provided by your install (administrators)

Administrators can add a theme for everyone on the install. Each theme is a small settings file. The
server lists the themes it finds, and a file that is not valid is skipped. The server log says why.
A new file shows up the next time someone opens the Settings menu.

<div data-technical>

Put one JSON file per theme in `config/themes/` at the root of the repository on the server. A
customer overlay can ship the folder. The server lists them at `GET /server/themes`. The folder is
read on each request. A file that is not valid is skipped and a line is written to the server log.

```json
{ "id": "acme", "name": "Acme", "default": true, "accent": "#0b5fff", "tone": "cool", "background": "#101a2e" }
```

- `id`, `name`, `accent` (`#rrggbb`) and `tone` (`neutral`, `warm` or `cool`) are required.
  `background` (`#rrggbb`, optional) is the dark page colour and replaces the tone.
- `"default": true` makes it the theme everyone gets until they pick another.
- Without `default`, the theme is only offered. It appears in the Colours row, and nobody gets it
  unless they pick it.
- Optional `dark` and `light` objects set exact colours for any palette key instead of the derived
  ones. See `docs/agent/platform/UI_STYLE.md` for the keys.

This repository ships `config/themes/crimson.json` (grey with a red accent).

</div>
