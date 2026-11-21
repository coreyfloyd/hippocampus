# Hippocampus

**A self-improving AI knowledge system that works in both Claude Code and Codex**

Keep what you and your AI learn, and make it useful in the next conversation. Throughout our sessions, you learn new information, discover better ways of working, and collect knowledge that is often lost when you close your chat. Platform-specific memory features help, but lock those learnings in proprietary formats and locations.

Hippocampus gives you tools and hooks to capture your research, meetings, lessons, and unfinished work in a shared home. And more importantly, it gives you workflows to file all that information where it belongs so your projects, documents and ticket systems stay up to date. It detects when your sessions compact and saves important information before it's lost. It's customizable so you define your own checklists that can capture the information that is important to you, and store it in the files or services you use.

As we use our agents for longer, we collect a lot of rules, memories, and practices that become disorganized and bloated. And as models improve, rules that were important become dead weight and take up context. Hippocampus helps you catch these files, then prune and organize them over time using the best practices from Anthropic and OpenAI. It helps you remove duplication and contradictions, while reducing the number of tokens your agents load.

## What you gain

- Improve how your agents work with you. Turn corrections and experience into reusable rules and skills, then review those instructions for duplication, conflict and unnecessary size.
- Spend less time re-establishing context with a wiki of specific knowledge about you, your interests and your work, and keep that information consistent across your chats and projects.
- Preserve where work stands, what was decided and what still needs attention when a session ends or compacts.
- Keep your knowledge when you change tools. Your sources, notes, rules and handoffs remain ordinary files you own. Direct integrations currently ship for Claude Code and Codex.
- Turn your agent questions into durable research you can reference later. Turn your meetings into notes and actions.
- Help reduce token usage by capturing important information when it's cheap.

## How the parts fit together

Hippocampus connects three kinds of memory: what you know, how your agents should work, and where your current work stands.

Each of these can be collected with you in the loop when you want more control, and automated after you establish your own rules and practices. Hippocampus supplies the workflows to enable this, while your own documents and task systems remain the record of your work.

![Hippocampus has five parts. A session writes a handoff through checkpoint or checklist and captures knowledge through knowledge-capture; sources become a meeting record through meeting-capture or a research report through research-topic. You approve or decline each proposed change: lessons reach rules and the agent harness through improve-harness, and absorb carries captures and research to the wiki through wiki-compile and to documents and follow-up work. Through pickup, the next session resumes from its handoff under the improved rules, with the wiki to read.](docs/images/overview.svg)

## Research that leads somewhere

Hippocampus started its life as a research skill, and these skills still remain one of its most useful workflows.

Most agent chats contain either explicit or implicit online searches to answer your questions. Both Claude and Codex agents know how to perform research well. What Hippocampus provides is a workflow for capturing that knowledge from your sessions and turning it into actions.

Start with a question, an article, a video, a podcast or a collection of sources. Use a short research workflow for an inline answer, or a deeper one when the question needs a durable report and a fuller evidence base.

Research retains its sources and distinguishes evidence from interpretation. Review the findings, then use absorb to apply the changes you authorize: update a document, retain a source, compile knowledge or file follow-up work in your own system. Research does not have to remain a backlog of conversations waiting for you to remember what to do next.

Hippocampus also works with [Gemini Notebook](https://notebooklm.google.com) (its integration still uses the former name, NotebookLM) in order to create focused research notebooks that provide more grounded answers than using either Claude or Codex on its own.

Meetings follow the same principle. If you capture meetings with Wispr Flow (through the Wispr Flow plugin) or Granola (through [Granola's MCP connector](https://docs.granola.ai/help-center/sharing/integrations/mcp)), or supply a transcript from a tool like Google Meet, you can create a source-linked record and identify the people, documents and actions affected by what was discussed.

![Ask a broad question or bring selected sources; Hippocampus writes a research report; absorb carries approved outcomes to people, documents, follow-up work, the wiki and a retained reference record.](docs/images/question-answer-action.svg)

![Bring a calendar event, note or transcript; Hippocampus writes a meeting record in your meeting folder; absorb carries approved outcomes to people, documents (including the original transcript, filed after approved routes complete), follow-up work, the wiki and a retained reference record.](docs/images/capture-meetings.svg)

## Knowledge for you and your AI

Your knowledge lives in a folder on your computer. It includes some standard folders, and skills for maintaining the content and for helping you organize context for your agents. Sources stay in `raw/`, research and created artifacts go in `output/`, and compiled knowledge in `wiki/`. The folder works best with Obsidian, but agents can read the Markdown directly.

The wiki is based on Karpathy's idea for agent knowledge management, and has been expanded to support your agent rules, memories, and multiple providers. It contains short, linked articles built from selected primary sources. It keeps attribution and records disagreements and gaps rather than merging every source into one answer. It includes tools for writing and auditing content.

## Built-in self-improvement

When you correct an agent or discover a better practice, `improve-harness` helps put the lesson where it will be useful: a focused skill, a shared rule, an agent definition or another appropriate part of your setup. Hippocampus understands that a line in your AGENTS.md file and a line in the system prompt have different impacts. It helps you find the best place for your rules.

Shared instructions can live alongside your knowledge. The rule composer delivers them to each tool's instruction format, so you can maintain one source rather than independently edit copies for each provider.

Improvement also means removing what no longer helps. `slim-harness` reviews instructions with you for duplication, conflicts and unnecessary detail. With automatic applying enabled, the system can retain size and duplication findings for `slim-unattended` to prepare review branches. It does not merge those branches for you.

These workflows preserve user-owned instructions and follow the approval policy you choose. They do not retrain the underlying model or guarantee that an agent will never repeat a mistake.

## Continue work across sessions

In order to make sure you don't lose your work, Hippocampus maintains handoff files for your sessions. It captures checkpoints automatically when a session compacts or stops, not on a timer, or manually when you invoke it. The handoff complements your agent's own compaction. It preserves a structured account of the work outside the conversation, and the supported hooks restore it after compaction.

Create custom checklists for the end of your sessions to make sure everything gets filed where you want and none of your work is lost. It points to your task and document systems rather than replacing them.

When your long-running sessions "fall out of cache" and are expensive to continue, you can "pickup" the work in a new session without needing to compact the old conversation or spending tokens searching its transcript for lost work.

It also provides a quick way to pass part of a task to a new session with a standard handoff prompt (that the new agent doesn't assume you wrote yourself).

![Mid-task, checkpoint writes a handoff; a finished task wraps through checklist and writes one. Pickup in Claude Code or Codex reads the handoff and follows it back to your record.](docs/images/session-lifecycle.svg)

## Your tools, your files

The packaged installation and hook integrations support Claude Code and Codex. The knowledge and rule sources use Markdown, with JSON for structured state. Other tools can use compatible files and skills, but full workflow and hook support depends on the integration.

Hippocampus does not require a particular task tracker or hosted knowledge service. Some research and transcription routes use optional external tools; their availability depends on your setup. One is [Defuddle](https://defuddle.md), which gives agents a web page's readable text instead of its full markup, so reading sites costs fewer tokens. It does not synchronize files across machines or create a general agent scheduler.

## Guides

Every skill, what it does and when to use it, is described in the knowledge and session guides.

- [Installation and setup](INSTALLATION.md)
- [Knowledge workflows](docs/knowledge-guide.md)
- [Session workflows](docs/session-guide.md)
- [Session installation and configuration](docs/session-installation.md)
- [Interfaces and integrations](INTERFACE.md)
- [Shared vocabulary](docs/glossary.md)
