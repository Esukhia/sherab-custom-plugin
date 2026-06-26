# Open edX Course Structure Reference

## Hierarchy Overview

```
Course
├── Section (Chapter) — corresponds to a week or topic block
│   ├── Subsection (Sequential) — a lesson or learning unit group
│   │   ├── Unit (Vertical) — one "page" of learning
│   │   │   ├── Video component
│   │   │   ├── HTML/Text component
│   │   │   ├── Problem (CAPA) component
│   │   │   ├── Discussion component
│   │   │   └── XBlock component
```

## Component Types

### Video Component
- Embeds YouTube, Vimeo, or self-hosted video
- Supports transcripts, captions
- OLX tag: `<video>`

### HTML Component
- Rich text, images, embedded media
- OLX tag: `<html>`

### CAPA Problems (Assessments)
- Multiple choice: `<multiplechoiceresponse>`
- True/False: `<multiplechoiceresponse>` with 2 options
- Short answer: `<stringresponse>` or `<freeresponse>`
- Numeric: `<numericalresponse>`
- Formula: `<formularesponse>`

### Discussion Component
- Forum thread tied to a unit
- OLX tag: `<discussion>`

### Drag-and-Drop XBlock
- Learners drag items onto targets
- Requires `drag-and-drop-v2` XBlock installed
- Good for: matching, sequencing, categorization

### Other XBlocks (common in forks)
- Poll XBlock
- Survey XBlock
- Word Cloud XBlock
- Peer Instruction XBlock

## OLX Export Structure (for dev team reference)

```
course/
├── course.xml
├── chapter/          ← Sections
│   └── *.xml
├── sequential/       ← Subsections
│   └── *.xml
├── vertical/         ← Units
│   └── *.xml
├── video/
├── html/
├── problem/
├── discussion/
└── static/           ← Assets (images, PDFs)
```

## Grading & Assessment Notes
- Problems can be graded or ungraded
- Graded subsections contribute to course grade
- Passing grade is set at course level (default: 50%)
- Drag-and-drop XBlock supports partial credit
