# Custom pages

Build the page you need from the platform's own blocks, or ask Atlas to build it for you. Pages live in the **Pages** menu in the top bar.

<div data-technical>

Page paths: `/pages` (list) and `/pages/<id>`. Needs `pages.custom:view` to open and `pages.custom:edit` to create, edit and share.

</div>

## Ask Atlas

Open Atlas and ask, for example: "Make me a page with only my STBs, a dropdown to go to a node, and the Localize result." Atlas builds a **draft** that only you can see. Open it from **Pages > All pages**, check it, and press **Save page**.

To change a saved page, ask again: "In my page, remove the Localize result and add the recent runs." Atlas says what it changed.

Ask "which blocks can I use?" to see what you can put on a page, and which blocks you cannot use and why.

## Build one by hand

1. **Pages > New page**, type a title.
2. Press **Edit page**, then **Add block**. Pick a block.
3. Use the arrows to move a block, the width box (1/6 to 6/6) to resize it, the gear for its settings and the bin to remove it.
4. Press **Done**.

## The blocks

| Block | What it shows |
|---|---|
| Device picker | A dropdown of your devices. Show only STBs, phones, TVs or web devices. The other blocks use the device you pick. |
| Go to node | Take control of the picked device and go to a navigation node. |
| Localize result | Which screen the device shows now, with the ranked candidates. |
| Live stream | The live view of the picked device. |
| Recent runs | The latest script runs on the picked device. |
| Saved report | A report you saved in Test Reports > Custom reports. |
| Text | A heading or a note. |

## Share a page

Open a saved page and press **Share**. Pick people, or the whole team, and choose **Can view** or **Can edit**. Only the owner shares or deletes a page.

Sharing gives nobody extra rights. Each person sees a block with their own permissions. A block they may not use shows as **locked** with the permission it needs. The share dialog tells you, for each person, how many blocks they would see locked.

## What you can and cannot do

You can only add blocks you may use yourself. If a block is greyed out in **Add block**, the line under it names the missing permission: ask a team admin. A viewer can open pages shared with them but cannot create or change pages.
