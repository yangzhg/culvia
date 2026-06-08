window.CulviaShortcuts = {
  catalog: [
    {
      groupKey: "shortcuts.group.browse",
      items: [
        { actionKey: "shortcuts.action.prevNext", keys: ["←", "→"] },
        { actionKey: "shortcuts.action.openHelp", keys: ["?"] },
      ],
    },
    {
      groupKey: "shortcuts.group.manual",
      items: [
        { actionKey: "shortcuts.action.manualRating", keys: ["1", "2", "3", "4", "5"] },
        { actionKey: "shortcuts.action.clearRating", keys: ["0"] },
        { actionKey: "shortcuts.action.pickRejectHold", keys: ["P", "X", "U"] },
      ],
    },
    {
      groupKey: "shortcuts.group.gallery",
      items: [
        { actionKey: "shortcuts.action.selectGallery", keys: ["Cmd+A", "Ctrl+A"] },
        { actionKey: "shortcuts.action.clearGallery", keys: ["Esc"] },
        { actionKey: "shortcuts.action.markSelected", keys: ["P", "X", "U"] },
      ],
    },
    {
      groupKey: "shortcuts.group.color",
      items: [
        { actionKey: "shortcuts.action.colorLabels", keys: ["R", "Y", "G", "B", "V"] },
        { actionKey: "shortcuts.action.clearColor", keys: ["C"] },
      ],
    },
    {
      groupKey: "shortcuts.group.restore",
      items: [{ actionKey: "shortcuts.action.undo", keys: ["Cmd+Z", "Ctrl+Z"] }],
    },
  ],
};
