# Watch a device a little late, with captions

A device on the **caption playback** profile is shown about two and a half minutes behind live. The words it speaks appear as captions on the picture. It is for people who cannot hear the audio, and for channels that have no subtitles of their own.

## Turn it on for a device

1. Go to **Settings → the host → the device → Monitor profile** and choose **`caption_playback`**, then save. Only that device starts transcribing.
2. To go back, set the profile to the default and save. Transcribing stops for that device.

<div data-technical>

The profile pins the spoken language (`DEVICE<N>_CAPTION_LANGUAGE`, for example `de`, or `auto`). Automatic language detection was wrong in about 8 % of the measured minutes, and a wrong language gives garbage text. The delay gives the system time to transcribe each minute and place every caption where the words are spoken. The model, the delay and the cost per device are in [Monitor profiles](../agent/devices/MONITOR_PROFILES.md#13-caption_playback-captions-for-one-device-task-103).

Turning the profile off restarts the audio service.

</div>

## What you see

Open the device's stream dialog on **Device Control**. For a caption-playback device, the dialog plays the recording instead of the live picture.

- A badge at the top left shows the real delay, for example **2:33 behind live**. It is measured, not the setting.
- Captions are drawn over the picture. They are machine text, and the bottom left says so ("Machine captions"). The **CC** button turns them on and off.
- If a minute is late, the player waits and shows **Waiting for captions…**. It never plays past the last minute that has a transcript.
- **Caption language** (English, Français, Deutsch) is remembered in your browser. It starts as your app language.
- Captions are translated by the host. If a minute is not translated yet, or the translation failed, the captions show the spoken language and say so ("shown in German, not translated yet").
- It looks the same in dark and light mode, with any colour theme.

<div data-technical>

Translation keeps the timing of the spoken words and has the same machine-text label. Translation runs one AI call per minute and language, started when the minute is transcribed. It costs about 20 000 tokens in and 33 000 out per device and hour for a German source (English and French). The cost shows on the AI usage page as `text.caption_translation`. A host turns translation off with `CAPTION_TRANSLATE_LANGS=` (empty).

</div>

![The delayed player in dark mode](../../frontend/public/screenshot/caption_modal_dark.webp)
![The same modal in light mode with a custom teal theme](../../frontend/public/screenshot/caption_modal_light_teal.webp)

## Minutes that already have subtitles

If the broadcaster's own subtitles are on screen for a minute, that minute is not transcribed. The player shows the broadcaster's subtitles instead.

<div data-technical>

The check is at least half of at least three checked frames. Each minute is recorded as `machine`, `broadcaster` or `none` (`caption_source`). Coverage per channel and hour is a count over the transcript files. `GET /server/transcript/captions?host_name=&device_id=&hour=&chunk_index=` returns the captions of one 10-minute chunk as WebVTT, with the source and readiness of each minute.

</div>

## Limits

- Captions are made by a small speech model (`tiny`). Names and compound words are often wrong. Speech over music may be missed, and a translation repeats those mistakes.
- One host can transcribe about four devices at the default delay. For more, use a longer `delay_s` or fewer devices.
- Only devices with recorded audio can be captioned. A device with no recorded segments has nothing to play.
