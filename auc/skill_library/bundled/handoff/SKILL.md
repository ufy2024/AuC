---
name: handoff
description: Compact the current conversation into a handoff document for another
  agent to pick up.
triggers:
- handoff
- compact
- current
- conversation
- document
- another
- agent
- pick
source: bundled
builtin: true
source_url: https://github.com/mattpocock/skills/blob/main/skills/productivity/handoff/SKILL.md
division: education
emoji: 📚
catalog: mattpocock
roles:
- education-tutor
---
Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to the temporary directory of the user's OS - not the current workspace.

Include a "suggested skills" section in the document, which suggests skills that the agent should invoke.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
