# KaiMS Demo Video Script

Target length: 4 minutes
Audience: End users and executives
Format: Screen recording + voiceover

Related versions:
- Executive 2-minute cut: [docs/DEMO_VIDEO_SCRIPT_EXECUTIVE_2MIN.md](docs/DEMO_VIDEO_SCRIPT_EXECUTIVE_2MIN.md)
- Technical 7-minute deep dive: [docs/DEMO_VIDEO_SCRIPT_TECHNICAL_7MIN.md](docs/DEMO_VIDEO_SCRIPT_TECHNICAL_7MIN.md)

## 0:00 - 0:20 Opening

On screen:
- Open KaiMS UI at http://localhost:8501
- Show left sidebar and top tabs

Voiceover:
- "This is KaiMS, an AI-powered operations platform that takes incidents from alert ingestion to validated closure with full governance and traceability."

## 0:20 - 0:55 Alerts and Quick Docs

On screen:
- Open Alerts and Quick Docs tab
- Click Load Latest Alerts
- Apply severity filter to HIGH or CRITICAL
- Show View Runbook, View Incident, View RCA actions

Voiceover:
- "Operators can review live alerts and instantly open runbook, incident, and RCA guidance without switching tools."

## 0:55 - 1:35 Start Workflow

On screen:
- Trigger a flow from alert stream or run sample flow
- Show Incident Summary tab updating

Voiceover:
- "Once selected, KaiMS runs a multi-agent workflow to correlate context, identify root cause, assess impact, and recommend the safest remediation."

## 1:35 - 2:20 Agent Flow

On screen:
- Open Agent Flow tab
- Show each agent role card
- Expand one Drill-down panel

Voiceover:
- "Agent Flow provides step-by-step visibility into action, input, output, and handoff between agents. This creates explainability and operational confidence."

## 2:20 - 2:55 Approval and Safety

On screen:
- Show approval state for HIGH/CRITICAL path
- Open Gateway Safety tab

Voiceover:
- "KaiMS enforces a human approval checkpoint for high-risk incidents. Gateway Safety also records policy decisions and request traceability for compliance."

## 2:55 - 3:25 FinOps

On screen:
- Open FinOps tab
- Show token and model usage

Voiceover:
- "FinOps gives clear model usage and cost visibility, enabling responsible AI operations at scale."

## 3:25 - 3:55 Closure

On screen:
- Open Closed Incidents tab
- Highlight closure report and lessons learned

Voiceover:
- "After remediation, closure is validated and documented, turning each incident into reusable operational knowledge."

## 3:55 - 4:00 Close

On screen:
- Return to main view

Voiceover:
- "KaiMS reduces incident resolution time, improves governance, and standardizes operations from alert to closure."

---

## Recording Checklist

- Use 1920x1080 resolution.
- Zoom browser to 110% for readability.
- Keep dark mode or light mode consistent for full video.
- Avoid pop-up overlays before recording.
- Keep cursor movement slow and intentional.

## Optional Executive Cut (90 seconds)

Use only these scenes:
- Opening
- Start Workflow
- Agent Flow
- Approval and Safety
- Closure

## Quick Recording Options

### Option A: OBS Studio

1. Start KaiMS UI at http://localhost:8501
2. In OBS, select Display Capture or Window Capture
3. Record at 1080p, 30fps
4. Export as MP4

### Option B: PowerPoint Recorder

1. Add screenshots or record screen directly in PowerPoint
2. Read the script as narration
3. Export to MP4 (File -> Export -> Create a Video)

### Option C: Teams Recording

1. Start a Teams meeting with yourself
2. Share screen and present the demo
3. Use meeting recording to auto-save video

