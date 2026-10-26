# BUG-0549 — Video card click does not transition to the iframe (state lost on every parent re-render)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0549                                                     |
| Reported  | 2026-10-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend (agent chat renderer)                               |
| Fixed in  | build 90145 |
| Commit    | `be500d423`                                                  |

---

## Symptom

After Atlas's first answer in the agent chat embeds a `[[video:<id>]]` token,
the lite-embed card renders (poster image + orange circular play button) but
clicking the play button never swaps the poster for the YouTube `<iframe>`.
The user clicks, nothing happens, the chat still shows the poster + button.

Headless test (`/tmp/atlas_debug_click.js`, 2026-10-15 19:48) reproduces
this consistently and prints the smoking gun:

```
[console] [VideoCard] play clicked YWJ1uz8KHCo
--- After click (2s) ---
{ "iframeCount": 0, "iframeSrcs": [], "posterCount": 1, "playBtnCount": 1 }
```

The click handler fires (`[VideoCard] play clicked` is logged), `setPlaying(true)`
is called, but the React tree does not re-render with the `<iframe>` branch.

## Root cause

`VideoCard` is a `React.FC` with internal `useState<boolean>(false)` for
`playing`. It is rendered inside `<ReactMarkdown>` via a custom `div`
component handler in `ChatMessages.tsx` (the previous design wrote the
token as a `<div data-video-id="..."></div>` placeholder and the custom
`div` component returned `<VideoCard id={videoId} />`).

react-markdown re-parses the markdown string on every parent re-render
(new agent events come in, then the streaming finalizes, then React's
reconciliation re-walks the markdown tree). On each re-render the
custom `div` component handler is called again and returns a brand-new
`<VideoCard />` element. React reconciles by position, but the new
`<VideoCard />` element is the *first* one in its position; the local
`useState` value of the prior instance is not transferred to the new
instance. So `playing` resets to `false` on every re-render, the click's
`setPlaying(true)` only takes effect for the instant between the click
and the next re-render, and the conditional render stays on the poster
branch.

In plain words: the `VideoCard` lives inside the ReactMarkdown subtree,
so its `useState` is reset on every parent update.

## Fix

`frontend/src/components/agent-chat/ChatMessages.tsx`:

1. New `splitVideoTokens(content)` returns `[{kind:'text'|'video', value:string}, ...]`,
   splitting the LLM content at every `[[video:<id>]]` token (1-2 brackets
   on each side, defensive against the model dropping a `]`).
2. New `renderContentWithVideos(content)` walks the segments and renders
   each text segment through `<ReactMarkdown>` and each video segment
   as a `<VideoCard>` directly — the VideoCard is now a *sibling* of the
   ReactMarkdown blocks, not a child of one.
3. The two call sites (streaming events at L1259, final content at L1266)
   both call `renderContentWithVideos()` instead of `replaceVideoTokens()`
   + `<ReactMarkdown>` with a custom `div` component handler.
4. `replaceVideoTokens`, the `data-video-id` placeholder, and the custom
   `div` component handler are deleted.

Because the `<VideoCard>` is now a sibling of the ReactMarkdown blocks in
the parent's React tree, its position is stable across re-renders, the
local `useState` value persists, and `setPlaying(true)` actually flips
the conditional.

## Verification

End-to-end headless test (`/tmp/atlas_video_verify.js`):

1. Open `https://virtualpytest.angelstreet.io/ai-agent?auto_signed=$TOKEN`
   (the auto-sign path, per `vpt-headless-verify`).
2. Click "New Chat", type "How do I fly a drone", press Enter.
3. Wait up to 60 s for `img[src*="img.youtube.com/vi/"]` (the poster).
4. Click the button with `aria-label^="Play video"`.
5. Wait 5 s, then assert the page contains an `iframe[src*="youtube.com/embed/"]`.

After the fix is deployed:

```
Card info: { "posterSrc": "https://img.youtube.com/vi/YWJ1uz8KHCo/hqdefault.jpg", "playBtnAria": "Play video YWJ1uz8KHCo", "cardHasButton": true }
Click play...
After click: {
  "hasIframe": true,
  "src": "https://www.youtube.com/embed/YWJ1uz8KHCo?autoplay=1&rel=0&playsinline=1&modestbranding=1",
  "isYouTubeEmbed": true,
  "hasAutoplay": true
}
Screenshot: /tmp/atlas-card-2-playing.png  (YouTube embed is mid-playback, caption "A drone on the Device page" visible)
```
