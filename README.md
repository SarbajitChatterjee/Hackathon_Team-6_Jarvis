# Jarvis — Future Pioneers (ODDO BHF) | AI for Private Investment (WIP)

Building towards **Future Pioneers: Paris Edition (Finals), Jan 22–23, 2026**. :contentReference[oaicite:5]{index=5}  
Current focus: **IT architecture + implementation**, integration, and demo stability.

> Programme context: **Future Pioneers: Paris Edition** is a hackathon + innovation journey focused on how AI will transform financial services, with a final presentation opportunity at ODDO BHF HQ in Paris. :contentReference[oaicite:6]{index=6}

**Last updated:** 2025-12

---

## Milestones
- ✅ Hackathon build phase (Saarbrücken): Nov 27–29, 2025
- 🚧 Build & iteration phase: Dec 2025 – Jan 2026
- 🎯 Finals / Paris Trip: Jan 22–23, 2026 :contentReference[oaicite:7]{index=7}

---

## What we’re building
**Goal:** an AI-native workflow that supports private investment decisions with faster insight generation and explainable outputs.  
**Scope:** prototype/demo (no confidential data).

**Demo flow (target):**
1) Input (client goal / risk / constraints)
2) Insights + structured recommendation
3) Explainability + sources
4) Exportable summary

---

## My role (Architecture + Implementation)
I’m contributing end-to-end on:
- System design (components, integration boundaries, data flow)
- API contracts + integration
- Data model (SQL) + persistence strategy
- Deployment approach (containerisation, env config)
- Observability/logging approach (e.g., Splunk/Grafana, as applicable)

---

## Architecture (high level)
```mermaid
flowchart LR
  UI[Frontend / Demo UI] --> API[Backend API]
  API --> DB[(SQL Database)]
  API --> AI[AI/LLM Services]
  API --> OBS[Logs/Monitoring]
