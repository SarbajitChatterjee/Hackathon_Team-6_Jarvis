<div align="center">

# 🤖 Jarvis
### AI Co-Manager for Private Investment
*Re-imagining the Future of Asset Management*

[![Status](https://img.shields.io/badge/Status-In%20Development-yellow)](https://github.com/SarbajitChatterjee/Hackathon_Team-6_Jarvis)
[![Future Pioneers](https://img.shields.io/badge/Future%20Pioneers-Paris%20Edition-blue)](https://www.oddo-bhf.com)
[![License](https://img.shields.io/badge/License-Proprietary-red)]()

[Live Demo](#) *Coming Soon 🚧* • [White Paper](docs/Team_6_White_Paper_V_1.pdf) • [Technical Docs](#architecture)

</div>

---

## 🎯 The Vision

**Jarvis transforms how investment decisions are made** by converting unstructured alternative data—patents, regulatory filings, sentiment signals—into actionable valuation insights in real-time.

While traditional asset management struggles with fee compression and information overload, Jarvis delivers a **quantifiable edge**: systematic alpha generation through AI-powered patent analysis, faster decision-making, and institutional-grade explainability.

<div align="center">

### 📊 Key Metrics (Projected)

| Metric | Impact |
|--------|--------|
| **Alpha Generation** | +2.5% annually |
| **Analysis Speed** | 20-30 seconds for 5-stock portfolio |
| **Cost Efficiency** | ~19% reduction in research costs |
| **Data Coverage** | Patents + 6 alternative data streams |

</div>

---

## 🚀 What Makes Jarvis Different

### 1. **First-Mover Advantage: Patent-to-Valuation Pipeline**
- ✅ Only system that transforms **unstructured patent data** directly into **DCF/multiples adjustments**
- ✅ AI extracts Innovation Quality (1-10), Commercial Readiness, and Litigation Risk scores
- ✅ Maps R&D trends to competitive moat width (Narrow → Wide → Fortress)

### 2. **Production-Ready Architecture**
```
🔄 Parallel Processing → ⚡ Sub-minute analysis → 📊 Real-time dashboards
```
- Database-driven orchestration (zero human intervention)
- Hybrid multi-source engine (Yahoo Finance, FinViz, AlphaVantage)
- Docker containerized on AWS (horizontally scalable)

### 3. **Institutional-Grade Transparency**
- Every AI conclusion traceable to source data
- Fama-French 3-factor regression for risk decomposition
- Human-in-the-loop design (AI assists, PM decides)

---

## 🏗️ System Architecture

### High-Level Flow
<div align="center">
<img src="docs/diagrams/high_level_architecture.png" alt="High Level Architecture" width="800"/>
</div>

**4-Phase Workflow:**
1. **Portfolio Ingestion** → Automatic fan-out to N ticker requests
2. **Parallel Data Fetching** → Financial (FDI) + Patent (PDI) workflows run concurrently
3. **Analysis Engine** → Backtesting + Fama-French + AI synthesis triggered by DB
4. **Decision Support** → Unified bull/bear cases + downloadable reports

### Entity Relationship Diagram
<div align="center">
<img src="docs/diagrams/erd.png" alt="ERD" width="700"/>
</div>

**Key Tables:**
- `portfolios` → Tracks aggregate status across 4 stages
- `track_requests` → Per-ticker progress (financial/patent/backtest completion)
- `patent_data` → Stores AI-structured JSON payloads (innovation scores, strategic trends)
- `ffm_results` → Alpha, beta, Sharpe ratio, factor exposures

---

## 🧠 The AI Edge: Patent Analysis

### From Raw Data to Investment Signals

**Input:** Unstructured patent records from PatentsView API  
**Output:** Investment-ready metrics via GPT-4 Mini

```json
{
  "innovation_quality": 8.5,
  "commercial_readiness": 7.2,
  "litigation_risk": 3.1,
  "moat_width": "Wide",
  "strategic_trend": "Pivoting from consumer electronics to spatial computing (2021-2024)",
  "tech_focus": ["Spatial Computing", "Health Tech", "Neural Engine"]
}
```

**Why This Matters:**
- 🎯 **Predictive Signal:** Patents filed today predict revenue 2-3 years ahead
- 📚 **Academically Validated:** Citation-weighted patents correlate with firm market value ([Hall, Jaffe & Trajtenberg, 2004](https://www.nber.org/papers/w7741))
- ⚡ **Scalable:** Analyze 10,000+ patents in minutes (impossible manually)

---

## 💼 Business Value Creation

### Short-Term (MVP)
| Value Driver | Mechanism | Impact |
|-------------|-----------|--------|
| **Stock Selection** | AI-powered screening via patent signals | +1.2% alpha |
| **Timing Optimization** | Faster sentiment + earnings interpretation | +0.6% alpha |
| **Risk Management** | Early detection of litigation/moat erosion | +0.4% alpha |
| **Portfolio Construction** | Better correlation estimates | +0.3% alpha |

### Long-Term Vision
- **AUM Growth:** 4% uplift on €25.6B addressable AUM = **€1B+ incremental AUM**
- **Continuous Learning:** AI improves 5-10% annually via feedback loops
- **Multi-Asset Expansion:** 6 additional alternative data streams (regulatory filings, sentiment, logistics)

---

## 🛠️ Technical Stack

<div align="center">

| Layer | Technology |
|-------|-----------|
| **Orchestration** | N8N (self-hosted workflows) |
| **Database** | Supabase (PostgreSQL + real-time subscriptions) |
| **Compute** | FastAPI + Docker (AWS EC2) |
| **AI/ML** | OpenAI GPT-4 Mini, NumPy/Pandas (vectorized backtesting) |
| **Frontend** | React (Lovable-built), Recharts visualization |
| **Data Sources** | Yahoo Finance, FinViz, AlphaVantage, PatentsView |

</div>

### Key Design Decisions
1. **Event-Driven Architecture** → Database triggers auto-advance workflows (no polling)
2. **Atomic State Management** → UUIDs + ACID transactions prevent race conditions
3. **Graceful Degradation** → 3x retry logic + multi-source failover (99.9% uptime target)
4. **AI Response Caching** → Reduce API costs by 60% while ensuring consistency

---

## 📈 Current Status & Roadmap

### ✅ MVP 0: Foundation (COMPLETE)
- [x] 20-30 second portfolio analysis (5 tickers)
- [x] AI-structured patent signals (Innovation/Commercial/Litigation scores)
- [x] Fama-French 3-factor regression
- [x] Bull/bear case generation

### 🚧 MVP 1: Valuation Integration (IN PROGRESS)
- [ ] Link patent scores → DCF growth rate adjustments
- [ ] Moat width → Terminal value multiple mappings
- [ ] Scenario analysis engine (bear/base/bull DCF outputs)

### 🔜 MVP 2: Signal Validation (Q2 2026)
- [ ] 3-year lagged backtesting (2020 patents → 2021-2023 returns)
- [ ] Factor regression to isolate pure alpha
- [ ] Automated signal weight adjustments

### 🎯 MVP 3: Data Expansion (Q3 2026)
- [ ] Regulatory filings (SEC, land registries)
- [ ] Social sentiment (Twitter, Glassdoor)
- [ ] Physical economy indicators (shipping, satellite)

---

## 🏆 Achievements & Recognition

<div align="center">

### Future Pioneers: Paris Edition
**Selected for Finals** | ODDO BHF HQ | Jan 22-23, 2026

<img src="https://via.placeholder.com/600x200/1a1a2e/00ff00?text=Future+Pioneers+Paris+Edition" alt="Future Pioneers" width="600"/>

</div>

**Program Highlights:**
- 🏅 Top 8 team selected from 50+ submissions
- 💼 Mentorship from ODDO BHF senior portfolio managers
- 🌍 International collaboration (Saarland University × SouthwestX × Triathlon)

---

## 👥 Team & Expertise

<table>
<tr>
<td width="25%" align="center">
<img src="https://via.placeholder.com/150" width="100" style="border-radius: 50%"/><br/>
<b>Sarbajit Chatterjee</b><br/>
<i>Product Architect</i><br/>
System design, AI integration, scalability
</td>
<td width="25%" align="center">
<img src="https://via.placeholder.com/150" width="100" style="border-radius: 50%"/><br/>
<b>Violet Si</b><br/>
<i>Commercial Lead</i><br/>
PM workflows, operating model
</td>
<td width="25%" align="center">
<img src="https://via.placeholder.com/150" width="100" style="border-radius: 50%"/><br/>
<b>Mohamed Raslan</b><br/>
<i>Financial Lead</i><br/>
Alpha modeling, AUM dynamics
</td>
<td width="25%" align="center">
<img src="https://via.placeholder.com/150" width="100" style="border-radius: 50%"/><br/>
<b>Rushan Mukherjee</b><br/>
<i>AI Expert</i><br/>
Backtesting, model explainability
</td>
</tr>
</table>

**Industry Advisor:** Dr. Ingolf Pernice (ODDO BHF Asset Management)

---

## 🖼️ UI/UX Preview

<div align="center">

*Coming Soon 🚧*
  <!---
### Dashboard Overview
<img src="docs/screenshots/screenshot1.png" alt="Dashboard" width="800"/>

### Portfolio Analysis
<img src="docs/screenshots/screenshot2.png" alt="Analysis" width="800"/>

### Patent Intelligence
<img src="docs/screenshots/screenshot4.png" alt="Patents" width="800"/>

--->

</div>

---

## 📚 Documentation

- 📄 [White Paper (35 pages)](docs/Team_6_White_Paper_V_1.pdf) - Complete technical + business case
- 🏗️ [Architecture Diagrams](docs/diagrams/) - High-level, ERD, workflow sequence
- 📊 [Value Creation Model](docs/Team_6_White_Paper_V_1.pdf#page=29) - Detailed AUM/alpha calculations
- ⚠️ [Current Limitations](docs/Team_6_White_Paper_V_1.pdf#page=33) - Known constraints + mitigation plans

---

**Prerequisites:**
- Docker 20.10+
- Node.js 18+
- OpenAI API key (GPT-4 access)
- Supabase project
- N8N Workflow Automation tool

---

📧 **Contact:** [sarbajitchatterjee09@gmail.com](mailto:sarbajitchatterjee09@gmail.com)  
💼 **LinkedIn:** [linkedin.com/in/sarbajit-chatterjee](https://www.linkedin.com/in/sarbajitc)  
🌐 **Portfolio:** [github.com/SarbajitChatterjee](https://github.com/SarbajitChatterjee)

---

## 📜 License & Citations

**Proprietary License** - Developed for Future Pioneers Paris Edition (ODDO BHF).  
Academic references and third-party data sources cited in [White Paper](docs/Team_6_White_Paper_V_1.pdf).

### Key Citations:
- Hall, B. H., Jaffe, A. B., & Trajtenberg, M. (2004). *Market value and patent citations.* RAND Journal of Economics.
- McKinsey & Company (2025). *How AI could reshape asset management economics.*
- Broadridge (2024). *US & European fund fee trends: A decade of transformation.*

---

<div align="center">

### ⭐ Star this repo if you find it interesting!

**Jarvis** | Built with ❤️ by Team 6 | Future Pioneers Paris Edition 2026

[📧 Contact](mailto:sarbajitchatterjee09@gmail.com) • [💼 LinkedIn](#)

</div>
