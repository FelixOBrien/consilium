# Documentation

These docs specify what Consilium is and what gets built. Linear issues point here; nothing is specified only in an issue.

## Map

| Doc | Answers |
| --- | --- |
| [vision.md](vision.md) | Why the product exists, goals, non-goals, how success is judged. |
| [context.md](context.md) | Hackathon rules and deadline, track and prizes, dataset, licences, platform limits. |
| [architecture.md](architecture.md) | System design, decisions made, configuration, risks. |
| [features/](features/index.md) | What the product does. One file per feature. |
| [stories/](stories/index.md) | Who needs each feature and how we know it works. One file per feature. |
| [models/](models/index.md) | The data that enables the features. One file per entity. |
| [screens/](screens/index.md) | Where the features appear and what each screen does. One file per screen. |

## How the docs derive from each other

```
vision ──► features ──► stories   (who, and acceptance)
                 ├────► models    (data needed)
                 └────► screens   (where it appears)
                              └──► Linear issues (the work)
```

Change flows the same way. Edit the feature first, then the stories, models and screens it links to, then the issue.

## IDs

| Kind | Format | Example | File |
| --- | --- | --- | --- |
| Feature | `F-NN` | `F-05` | `features/F05-evidence-search.md` |
| Story | `US-NN.n` where `NN` is the feature | `US-05.2` | `stories/F05-evidence-search.md` |
| Model | the entity name, `snake_case` | `patch` | `models/patch.md` |
| Screen | `S-NN` | `S-02` | `screens/S02-case-workspace.md` |

IDs are permanent. A cut feature keeps its number and gets `status: cut`.

## Shared vocabulary

**Status** — `planned`, `in-progress`, `done`, `cut`.

**Priority**

| Priority | Meaning |
| --- | --- |
| `P0` | The demo fails without it. Built first. |
| `P1` | Makes the demo convincing. Built once every P0 works end to end. |
| `P2` | Stretch. Built only if nothing above it is open. |

## Style, all docs

- Start with YAML front matter exactly as the folder's `index.md` template shows.
- Use the section headings in the template, in order. Write "None." under a heading that does not apply; do not delete it.
- Link other docs by relative path. Refer to features, stories and screens by ID.
- State behaviour as numbered, testable rules. No visual design in feature or screen docs: layout, colour and type belong to Figma.
- Present tense, plain words, no marketing.
- Each folder's `index.md` holds the template and the register of every doc in the folder. Add a row when you add a file.
